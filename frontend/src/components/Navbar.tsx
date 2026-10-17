import { useEffect, useRef, useState, type ComponentType, type SVGProps } from 'react'
import { BankIcon, DiscordIcon, GitHubIcon, LinkedInIcon, MoonIcon, SunIcon } from './Icons'
import { TEAM, type Person } from '../lib/team'
import type { Theme } from '../lib/theme'

type Network = 'github' | 'linkedin' | 'discord'
const NETWORKS: { key: Network; label: string; Icon: ComponentType<SVGProps<SVGSVGElement>> }[] = [
  { key: 'github', label: 'GitHub', Icon: GitHubIcon },
  { key: 'linkedin', label: 'LinkedIn', Icon: LinkedInIcon },
  { key: 'discord', label: 'Discord', Icon: DiscordIcon },
]

function handle(p: Person, n: Network): string {
  const url = p[n]
  if (n === 'github') return url.replace(/^https?:\/\/(www\.)?github\.com\//, '@').replace(/\/$/, '')
  if (n === 'linkedin') return url.includes('/in/') ? 'LinkedIn profile' : 'LinkedIn'
  return p.discordName ? `@${p.discordName}` : 'Discord profile'
}

/** One icon per network; opening it lists both teammates. */
function SocialMenu({ net, open, onToggle, onClose }: { net: (typeof NETWORKS)[number]; open: boolean; onToggle: () => void; onClose: () => void }) {
  const people = TEAM.filter((p) => p[net.key])
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && onClose()
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, onClose])
  if (!people.length) return null
  const { Icon } = net
  return (
    <div className="social" ref={ref}>
      <button
        className="icon-btn"
        aria-label={`${net.label} profiles of the team`}
        aria-haspopup="menu"
        aria-expanded={open}
        title={net.label}
        onClick={onToggle}
      >
        <Icon />
      </button>
      {open && (
        <div className="social-menu" role="menu">
          <p>The team on {net.label}</p>
          {people.map((p) => (
            <a key={p.name} role="menuitem" href={p[net.key]} target="_blank" rel="noreferrer" onClick={onClose}>
              <span className="avatar" aria-hidden>
                {p.initials}
              </span>
              <span className="who">
                <b>{p.name}</b>
                <small>{handle(p, net.key)}</small>
              </span>
            </a>
          ))}
        </div>
      )}
    </div>
  )
}

interface Props {
  theme: Theme
  onToggleTheme: () => void
  onHome: () => void
  demo: boolean
}

export default function Navbar({ theme, onToggleTheme, onHome, demo }: Props) {
  const [openMenu, setOpenMenu] = useState<Network | null>(null)
  return (
    <header className="topbar no-print">
      <button className="brand" onClick={onHome} aria-label="ComplAI home">
        <span className="brand-mark">
          <BankIcon />
        </span>
        <span className="brand-word">
          Compl<span>AI</span>
        </span>
      </button>
      <span className="topbar-note">Policy compliance review</span>
      {demo && <span className="demo-pill">Demo data</span>}
      <nav className="nav-right" aria-label="Team and settings">
        {NETWORKS.map((n) => (
          <SocialMenu
            key={n.key}
            net={n}
            open={openMenu === n.key}
            onToggle={() => setOpenMenu((m) => (m === n.key ? null : n.key))}
            onClose={() => setOpenMenu(null)}
          />
        ))}
        <span className="nav-sep" aria-hidden />
        <button
          className="icon-btn theme-toggle"
          onClick={onToggleTheme}
          aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          title={theme === 'dark' ? 'Light mode' : 'Dark mode'}
        >
          {theme === 'dark' ? <SunIcon /> : <MoonIcon />}
        </button>
      </nav>
    </header>
  )
}
