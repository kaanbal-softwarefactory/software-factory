// A newer repository revision is not necessarily a newer engine build.
export function updateSummary(data) {
  if (!data) return { kind: 'unknown', title: 'Sin comprobación de actualizaciones.' }
  const upstream = data.upstream || {}
  if (data.tracking === 'commits' && (!upstream.available || !upstream.head_sha)) {
    return { kind: 'unknown', title: 'No se pudo comprobar si hay actualizaciones.', detail: upstream.reason || 'No se pudo consultar la revisión de main.' }
  }
  if (data.update_available) return { kind: 'available', title: 'Hay una actualización del engine.' }
  if (data.tracking === 'commits') {
    if (upstream.reason) return { kind: 'unknown', title: 'La revisión instalada requiere atención.', detail: upstream.reason }
    if (upstream.ahead_by > 0 || upstream.commits?.length) {
      return { kind: 'repository', title: 'Hay commits nuevos; no requieren actualizar el engine.', detail: 'La revisión instalada sigue siendo válida. Consulta los commits pendientes abajo; los cambios fuera del engine no requieren reconstruir los servicios.' }
    }
  } else if (!data.latest) {
    return { kind: 'unknown', title: 'No hay una release disponible para comparar.', detail: 'La ausencia de releases no confirma que esta célula esté al día.' }
  }
  if (!data.current?.known) return { kind: 'unknown', title: 'No se conoce la revisión instalada.' }
  return { kind: 'current', title: 'El engine está al día.' }
}

export function canReapplyLatest(data) {
  return data?.tracking === 'commits' && data.upstream?.available === true && /^[a-f0-9]{40}$/i.test(data.upstream.head_sha || '')
}

export function upgradeBlocked(data) {
  return Boolean(data?.blocked_by_drift || data?.drift?.any_custom)
}
