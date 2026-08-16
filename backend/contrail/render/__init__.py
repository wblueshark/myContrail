"""Server-side PNG rendering.

Pillow composites and lays out; pycairo draws vectors. The split is not
stylistic: Pillow's ImageDraw.line() has no antialiasing and produces hard
stair-stepped edges, which is the difference between an image worth sharing and
one that is not. 4x supersampling was the alternative and costs 557 MB per A4
300dpi page - over budget. cairo antialiases natively; 47 alpha transition
levels were measured on this machine.

A headless browser was rejected: +400 MB of container, +300 MB per instance,
slow start, and font rendering that regularly breaks in containers. The layout
needs of three templates do not justify any of that.
"""
