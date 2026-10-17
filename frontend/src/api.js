const API = '/api'

const waveQuery = (wave) => (wave ? `?wave=${encodeURIComponent(wave)}` : '')

export async function fetchWaves() {
  const res = await fetch(`${API}/waves`)
  if (!res.ok) throw new Error('Error al cargar olas')
  return res.json()
}

export async function fetchFeatures() {
  const res = await fetch(`${API}/features`)
  if (!res.ok) throw new Error('Error al cargar features')
  return res.json()
}

export async function fetchQuestions(wave) {
  const res = await fetch(`${API}/questions${waveQuery(wave)}`)
  if (!res.ok) throw new Error('Error al cargar preguntas')
  return res.json()
}

export async function fetchAttributes(wave) {
  const res = await fetch(`${API}/attributes${waveQuery(wave)}`)
  if (!res.ok) throw new Error('Error al cargar atributos')
  return res.json()
}

export async function fetchRecodes() {
  const res = await fetch(`${API}/recodes`)
  if (!res.ok) throw new Error('Error al cargar recodes')
  return res.json()
}

export async function fetchPresets(wave) {
  const res = await fetch(`${API}/presets${waveQuery(wave)}`)
  if (!res.ok) throw new Error('Error al cargar presets')
  return res.json()
}

export async function fetchCities(wave) {
  const res = await fetch(`${API}/cities${waveQuery(wave)}`)
  if (!res.ok) throw new Error('Error al cargar ciudades')
  return res.json()
}

export async function runQuery(body) {
  const res = await fetch(`${API}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || res.statusText)
  }
  return res.json()
}

export async function exportCSV(body) {
  const res = await fetch(`${API}/query/csv`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error('Error al exportar CSV')
  return res.blob()
}

export async function chat(body) {
  const res = await fetch(`${API}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || res.statusText)
  }
  return res.json()
}
