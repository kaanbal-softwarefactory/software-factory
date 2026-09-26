/**
 * Sitios web: un homepage por dominio.
 *
 * Misma regla que la API (kaanbal-api/app/services/domain_service.py:
 * site_slug, root_app_name, root_app_candidates, site_group). Si cambia una y
 * no la otra, la consola anuncia un nombre que la API no asigna.
 */
export const HOMEPAGE_SUFFIX = '-homepage'
const MAX_NAME = 63

const clean = (value) => value
  .replace(/_/g, '-')
  .replace(/[^a-z0-9-]/g, '')
  .replace(/-+/g, '-')
  .replace(/^-|-$/g, '')

// 'northwind.store' → 'northwind'; con full → 'northwind-store'.
export const siteSlug = (fqdn, { full = false } = {}) => {
  const host = (fqdn || '').trim().toLowerCase()
  return clean(full ? host.replace(/\./g, '-') : host.split('.')[0]) || 'site'
}

export const homepageName = (fqdn, { full = false, ordinal = 1 } = {}) => {
  const tail = ordinal > 1 ? `-${ordinal}` : ''
  const slug = siteSlug(fqdn, { full }).slice(0, MAX_NAME - HOMEPAGE_SUFFIX.length - tail.length).replace(/-+$/, '')
  return `${slug}${tail}${HOMEPAGE_SUFFIX}`
}

// Primer nombre libre: 'northwind-homepage', luego 'northwind-store-homepage', luego numerado.
export const allocateHomepageName = (fqdn, takenNames = []) => {
  const taken = new Set([...takenNames].map(name => String(name).toLowerCase()))
  const first = homepageName(fqdn)
  if (!taken.has(first)) return first
  const full = homepageName(fqdn, { full: true })
  if (!taken.has(full)) return full
  for (let ordinal = 2; ; ordinal++) {
    const name = homepageName(fqdn, { full: true, ordinal })
    if (!taken.has(name)) return name
  }
}

// Host público de una app, misma regla que la API (domain_service.public_host):
// prod vive en <app>.<dominio> —o en el dominio desnudo si ocupa la raíz— y el
// resto de ambientes en <env>-<app>.<dominio>.
export const publicHost = (appName, env, fqdn, { isRoot = false } = {}) => {
  if (env === 'prod') return isRoot ? fqdn : `${appName}.${fqdn}`
  return `${env}-${appName}.${fqdn}`
}

// Grupo del sitio: el nombre del homepage sin el sufijo ('northwind-homepage' → 'northwind').
export const siteGroup = (homepageAppName) => {
  const name = (homepageAppName || '').trim().toLowerCase()
  return name.endsWith(HOMEPAGE_SUFFIX) && name.length > HOMEPAGE_SUFFIX.length
    ? name.slice(0, -HOMEPAGE_SUFFIX.length)
    : name
}
