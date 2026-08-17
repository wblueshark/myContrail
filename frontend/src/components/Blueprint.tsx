/**
 * The wireframe frame the design system puts on every card, figure and dialog:
 * square corners, a hairline border, and four registration marks.
 *
 * A component rather than four hand-written `<i class="corner">` children per
 * call site - the marks are part of the frame, and the one thing the system
 * says never to drop.
 */

import type { CSSProperties, ReactNode } from 'react'

interface Props {
  children: ReactNode
  className?: string
  style?: CSSProperties
  as?: 'div' | 'section' | 'article'
}

export default function Blueprint({ children, className = '', style, as = 'div' }: Props) {
  const Tag = as
  return (
    <Tag className={`blueprint ${className}`.trim()} style={style}>
      <i className="corner tl" />
      <i className="corner tr" />
      <i className="corner bl" />
      <i className="corner br" />
      {children}
    </Tag>
  )
}
