/**
 * App runtime ops — exposure switch, env lifecycle.
 * Uses the global axios instance (Bearer + baseURL from main.js).
 */
import axios from 'axios'

export async function patchAppExposure(appName, { per_env, port_exposure, domain_id } = {}) {
  const body = { per_env }
  if (port_exposure) body.port_exposure = port_exposure
  // Mudar de dominio padre reusa esta misma coreografía: publica el DNS nuevo,
  // lo prueba y recién entonces retira el viejo.
  if (domain_id) body.domain_id = domain_id
  const { data } = await axios.patch(`/api/v1/apps/${appName}/exposure`, body)
  return data
}

export async function fetchAppExposureStatus(appName) {
  const { data } = await axios.get(`/api/v1/apps/${appName}/exposure/status`)
  return data
}

export async function scaleAppEnv(appName, env, replicas) {
  const { data } = await axios.post(
    `/api/v1/apps/${appName}/environments/${env}/scale`,
    { replicas }
  )
  return data
}

export async function stopAppEnv(appName, env) {
  const { data } = await axios.post(`/api/v1/apps/${appName}/environments/${env}/stop`)
  return data
}

export async function startAppEnv(appName, env, replicas = 1) {
  const { data } = await axios.post(
    `/api/v1/apps/${appName}/environments/${env}/start`,
    { replicas }
  )
  return data
}

export async function enableAppEnv(appName, env, exposure = 'tailscale') {
  const { data } = await axios.post(
    `/api/v1/apps/${appName}/environments/${env}`,
    { exposure }
  )
  return data
}

export async function removeAppEnv(appName, env, { deleteOverlay = false } = {}) {
  const { data } = await axios.delete(
    `/api/v1/apps/${appName}/environments/${env}`,
    { params: { delete_overlay: deleteOverlay } }
  )
  return data
}

export async function fetchApp(appName) {
  const { data } = await axios.get(`/api/v1/apps/${appName}`)
  return data
}
