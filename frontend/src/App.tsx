import { useCallback, useEffect, useRef, useState } from 'react'
import type { LocationInputs, Result } from './types'
import { USE_MOCK } from './lib/api'
import { useTheme } from './lib/theme'
import Navbar from './components/Navbar'
import Intro from './components/Intro'
import { detectTimezone } from './lib/geo'
import LocationScreen from './screens/LocationScreen'
import DashboardScreen from './screens/DashboardScreen'
import ProgressScreen from './screens/ProgressScreen'
import ReportScreen from './screens/ReportScreen'

type Screen = 'location' | 'dashboard' | 'progress' | 'report'
const STORAGE_KEY = 'complai.location'

function loadInputs(): LocationInputs {
  const blank: LocationInputs = {
    country: '',
    region: '',
    city: '',
    timezone: detectTimezone(),
    policy_type: '',
    institution_type: '',
  }
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return { ...blank, ...(JSON.parse(raw) as Partial<LocationInputs>) }
  } catch {
    /* storage unavailable */
  }
  return blank
}

export default function App() {
  const [inputs, setInputs] = useState<LocationInputs>(loadInputs)
  const [screen, setScreen] = useState<Screen>(() => (loadInputs().country ? 'dashboard' : 'location'))
  const [leaving, setLeaving] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [result, setResult] = useState<Result | null>(null)
  const timer = useRef<number>()
  const [theme, toggleTheme] = useTheme()
  // intro -> leaving (slides up while the app rises into place) -> done (removed)
  const [intro, setIntro] = useState<'show' | 'leaving' | 'done'>('show')
  const dismissIntro = useCallback(() => {
    setIntro('leaving')
    window.setTimeout(() => setIntro('done'), 900)
  }, [])

  const go = useCallback((next: Screen) => {
    setLeaving(true)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => {
      setScreen(next)
      setLeaving(false)
      window.scrollTo({ top: 0 })
    }, 220)
  }, [])

  useEffect(() => () => window.clearTimeout(timer.current), [])

  const saveInputs = (next: LocationInputs) => {
    setInputs(next)
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
    } catch {
      /* storage unavailable */
    }
  }

  return (
    <div className="app">
      {intro !== 'done' && <Intro leaving={intro === 'leaving'} onDone={dismissIntro} />}
      <div className={`shell ${intro === 'show' ? 'pre-intro' : ''}`} aria-hidden={intro === 'show'}>
        <Navbar
          theme={theme}
          onToggleTheme={toggleTheme}
          onHome={() => go(inputs.country ? 'dashboard' : 'location')}
          demo={USE_MOCK}
        />
        <main
          key={screen}
          className={`screen ${leaving ? 'screen-out' : 'screen-in'} ${screen === 'report' ? 'wide' : ''}`}
        >
          {screen === 'location' && (
            <LocationScreen
              initial={inputs}
              onContinue={(next) => {
                saveInputs(next)
                go('dashboard')
              }}
            />
          )}
          {screen === 'dashboard' && (
            <DashboardScreen
              inputs={inputs}
              file={file}
              onFile={setFile}
              onEdit={() => go('location')}
              onAnalyse={() => go('progress')}
            />
          )}
          {screen === 'progress' && file && (
            <ProgressScreen
              inputs={inputs}
              file={file}
              onDone={(r) => {
                setResult(r)
                go('report')
              }}
              onCancel={() => go('dashboard')}
            />
          )}
          {screen === 'report' && result && <ReportScreen result={result} onNew={() => go('dashboard')} />}
        </main>
      </div>
    </div>
  )
}
