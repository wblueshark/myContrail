"""Per-fence export actions, city-level coarsening, overview indexes.

Revision ID: 0002
Revises: 0001

Three additions, all driven by the redesign (CR-005, CR-007):

  1. fence-subset overloads. The v1 functions apply every enabled fence at once,
     which cannot express "blur home, remove work" - and the export dialog now
     offers exactly that. The subset overloads carry the real bodies; the
     original two-argument forms delegate with "all enabled fences", so their
     behaviour is unchanged and the existing privacy tests still describe them.

  2. contrail_coarsen_city. Grid snapping, never noise: noise averages out over
     several exports of the same trip, a grid does not. Same reasoning as the
     blur policy, one scale coarser.

  3. two b-tree indexes for the overview aggregates, which filter and group on
     place.geo_country / geo_city.
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# A city is a ~10 km object. The value is fixed rather than user-supplied: a
# grid the user can vary is a grid an attacker can difference away.
CITY_GRID_M = 10000


def upgrade() -> None:
    op.execute(
        f"""
-- ── fence subset overloads ────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION contrail_fence_buffer(uid uuid, fence_ids uuid[])
RETURNS geometry AS $$
    SELECT ST_Union(ST_Buffer(f.center::geography, f.radius_m)::geometry)
    FROM geofence f
    WHERE f.user_id = uid AND f.enabled
      AND (fence_ids IS NULL OR f.id = ANY(fence_ids));
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION contrail_jitter_endpoints(g geometry, uid uuid, fence_ids uuid[])
RETURNS geometry AS $$
DECLARE
    buf      geometry;
    edge     geometry;
    comp     geometry;
    parts    geometry[] := '{{}}';
    n        integer;
    i        integer;
    len      double precision;
    r        double precision;
    seed     bigint;
    head     double precision;
    tail     double precision;
    trimmed  geometry;
BEGIN
    IF g IS NULL OR ST_IsEmpty(g) THEN
        RETURN g;
    END IF;

    buf := contrail_fence_buffer(uid, fence_ids);
    IF buf IS NULL THEN
        RETURN g;
    END IF;
    edge := ST_Boundary(buf);

    SELECT COALESCE(max(f.radius_m), 500), COALESCE(min(f.jitter_seed), 0)
      INTO r, seed
      FROM geofence f
     WHERE f.user_id = uid AND f.enabled
       AND (fence_ids IS NULL OR f.id = ANY(fence_ids));

    n := COALESCE(ST_NumGeometries(g), 1);
    FOR i IN 1..n LOOP
        comp := COALESCE(ST_GeometryN(g, i), g);
        IF GeometryType(comp) <> 'LINESTRING' THEN
            parts := parts || comp;
            CONTINUE;
        END IF;

        len := ST_Length(comp::geography);
        IF len IS NULL OR len < 1 THEN
            CONTINUE;
        END IF;

        head := 0;
        tail := 0;
        IF ST_DWithin(ST_StartPoint(comp)::geography, edge::geography, 1.0) THEN
            head := r * 0.3 * contrail_seeded_unit(seed, i * 2);
        END IF;
        IF ST_DWithin(ST_EndPoint(comp)::geography, edge::geography, 1.0) THEN
            tail := r * 0.3 * contrail_seeded_unit(seed, i * 2 + 1);
        END IF;

        IF head + tail >= len THEN
            CONTINUE;
        END IF;

        trimmed := ST_LineSubstring(comp, head / len, 1.0 - tail / len);
        IF trimmed IS NOT NULL AND NOT ST_IsEmpty(trimmed) THEN
            parts := parts || trimmed;
        END IF;
    END LOOP;

    IF array_length(parts, 1) IS NULL THEN
        RETURN NULL;
    END IF;
    RETURN ST_Multi(ST_Collect(parts));
END;
$$ LANGUAGE plpgsql STABLE;

CREATE OR REPLACE FUNCTION contrail_fence_remove(g geometry, uid uuid, fence_ids uuid[])
RETURNS geometry AS $$
    SELECT contrail_jitter_endpoints(
        COALESCE(ST_Difference(g, contrail_fence_buffer(uid, fence_ids)), g), uid, fence_ids);
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION contrail_fence_blur(
    g geometry, uid uuid, fence_ids uuid[], grid_m integer DEFAULT 2000)
RETURNS geometry AS $$
DECLARE
    buf     geometry;
    snapped geometry;
    cleaned geometry;
BEGIN
    IF g IS NULL OR ST_IsEmpty(g) THEN
        RETURN g;
    END IF;

    buf := contrail_fence_buffer(uid, fence_ids);
    IF buf IS NULL OR NOT ST_Intersects(g, buf) THEN
        RETURN g;
    END IF;

    snapped := ST_SnapToGrid(g, grid_m / 111320.0);
    IF snapped IS NULL OR ST_IsEmpty(snapped)
       OR (GeometryType(snapped) LIKE '%LINESTRING%' AND ST_NPoints(snapped) < 2) THEN
        snapped := g;
    END IF;

    cleaned := ST_Difference(snapped, buf);
    IF cleaned IS NULL OR ST_IsEmpty(cleaned) THEN
        RETURN NULL;
    END IF;
    RETURN contrail_jitter_endpoints(cleaned, uid, fence_ids);
END;
$$ LANGUAGE plpgsql STABLE;

-- The original two-argument forms now delegate: one body, one behaviour.
CREATE OR REPLACE FUNCTION contrail_jitter_endpoints(g geometry, uid uuid)
RETURNS geometry AS $$
    SELECT contrail_jitter_endpoints(g, uid, NULL::uuid[]);
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION contrail_fence_remove(g geometry, uid uuid)
RETURNS geometry AS $$
    SELECT contrail_fence_remove(g, uid, NULL::uuid[]);
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION contrail_fence_blur(
    g geometry, uid uuid, grid_m integer DEFAULT 2000)
RETURNS geometry AS $$
    SELECT contrail_fence_blur(g, uid, NULL::uuid[], grid_m);
$$ LANGUAGE sql STABLE;

-- ── city-level coarsening ─────────────────────────────────────────────────
-- Applies to EVERY coordinate in an export, fence or no fence: the user asked
-- for "readable to the district, not to the street".
CREATE OR REPLACE FUNCTION contrail_coarsen_city(g geometry, grid_m integer DEFAULT {CITY_GRID_M})
RETURNS geometry AS $$
DECLARE
    snapped geometry;
BEGIN
    IF g IS NULL OR ST_IsEmpty(g) THEN
        RETURN g;
    END IF;
    snapped := ST_SnapToGrid(g, grid_m / 111320.0);
    IF snapped IS NULL OR ST_IsEmpty(snapped)
       OR (GeometryType(snapped) LIKE '%LINESTRING%' AND ST_NPoints(snapped) < 2) THEN
        RETURN g;
    END IF;
    RETURN snapped;
END;
$$ LANGUAGE plpgsql STABLE;
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_place_user_country ON place (user_id, geo_country);
        CREATE INDEX IF NOT EXISTS ix_place_user_city ON place (user_id, geo_city);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_place_user_city;
        DROP INDEX IF EXISTS ix_place_user_country;
        DROP FUNCTION IF EXISTS contrail_coarsen_city(geometry, integer);
        DROP FUNCTION IF EXISTS contrail_fence_blur(geometry, uuid, uuid[], integer);
        DROP FUNCTION IF EXISTS contrail_fence_remove(geometry, uuid, uuid[]);
        DROP FUNCTION IF EXISTS contrail_jitter_endpoints(geometry, uuid, uuid[]);
        DROP FUNCTION IF EXISTS contrail_fence_buffer(uuid, uuid[]);
        """
    )
