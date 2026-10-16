import { useMemo, useState } from 'react'
import { INSTITUTION_TYPES, POLICY_TYPES, type LocationInputs } from '../types'
import { COUNTRIES, REGIONS, allTimezones } from '../lib/geo'

interface Props {
  initial: LocationInputs
  onContinue: (inputs: LocationInputs) => void
}

export default function LocationScreen({ initial, onContinue }: Props) {
  const [v, setV] = useState<LocationInputs>(initial)
  const zones = useMemo(allTimezones, [])
  const regions = REGIONS[v.country] ?? []
  const set = (k: keyof LocationInputs) => (e: { target: { value: string } }) =>
    setV((p) => ({ ...p, [k]: e.target.value, ...(k === 'country' ? { region: '', city: '' } : {}) }))
  const valid = Boolean(v.country && v.timezone.trim() && v.policy_type && v.institution_type)

  return (
    <section className="card narrow">
      <p className="eyebrow">Step 1 of 2</p>
      <h1>Where does your bank operate?</h1>
      <p className="lede">
        We use your jurisdiction to find the regulations that apply. You never need to upload regulatory documents.
      </p>
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault()
          if (valid) onContinue({ ...v, region: v.region.trim(), city: v.city.trim(), timezone: v.timezone.trim() })
        }}
      >
        <label className="field">
          <span>Country <em>required</em></span>
          <select value={v.country} onChange={set('country')} required>
            <option value="">Select a country</option>
            {COUNTRIES.map((c) => (
              <option key={c.code} value={c.code}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <div className="row2">
          <label className="field">
            <span>State or region</span>
            <input list="regions" value={v.region} onChange={set('region')} placeholder="Optional" />
            <datalist id="regions">
              {regions.map((r) => (
                <option key={r} value={r} />
              ))}
            </datalist>
          </label>
          <label className="field">
            <span>City</span>
            <input value={v.city} onChange={set('city')} placeholder="Only if a city regulator exists" />
          </label>
        </div>
        <label className="field">
          <span>Time zone <em>required</em></span>
          <input list="zones" value={v.timezone} onChange={set('timezone')} required />
          <datalist id="zones">
            {zones.map((z) => (
              <option key={z} value={z} />
            ))}
          </datalist>
          <small>Detected from your browser. Used to judge effective dates and recent amendments.</small>
        </label>
        <div className="row2">
          <label className="field">
            <span>Policy type <em>required</em></span>
            <select value={v.policy_type} onChange={set('policy_type')} required>
              <option value="">Select</option>
              {POLICY_TYPES.map((p) => (
                <option key={p}>{p}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Institution type <em>required</em></span>
            <select value={v.institution_type} onChange={set('institution_type')} required>
              <option value="">Select</option>
              {INSTITUTION_TYPES.map((p) => (
                <option key={p}>{p}</option>
              ))}
            </select>
          </label>
        </div>
        <button className="btn primary" type="submit" disabled={!valid}>
          Continue
        </button>
      </form>
    </section>
  )
}
