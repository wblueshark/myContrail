/** The three onboarding bubbles: a track, a place, the timeline (02 section 2). */

import { useCopy } from '@/i18n'
import { useAppStore } from '@/store/appStore'

const POSITIONS = [
  { left: '38%', top: '38%' },
  { left: '52%', top: '26%' },
  { left: '30%', bottom: '14%' },
]

export default function GuideBubbles() {
  const t = useCopy()
  const step = useAppStore((state) => state.guideStep)
  const advance = useAppStore((state) => state.advanceGuide)
  const end = useAppStore((state) => state.endGuide)

  if (step > 2) return null
  const copy = [t.guide.step1, t.guide.step2, t.guide.step3][step] ?? ''

  return (
    <div className="guide" style={POSITIONS[step]}>
      <div>{copy}</div>
      <div className="row" style={{ gap: 8, marginTop: 10 }}>
        <button className="btn btn-primary btn-sm" onClick={advance}>
          {t.guide.next} {t.guide.progress(step + 1, 3)}
        </button>
        {step < 2 && (
          <button className="btn btn-sm" onClick={end}>
            {t.guide.skip}
          </button>
        )}
      </div>
    </div>
  )
}
