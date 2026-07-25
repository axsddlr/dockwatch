import { useEffect, useState, type ReactNode } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { api } from '../api/client'

export function RequireAuth({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  const location = useLocation()
  const [checked, setChecked] = useState(false)

  useEffect(() => {
    const redirectToLogin = () => {
      const next = encodeURIComponent(location.pathname + location.search)
      navigate(`/login?next=${next}`, { replace: true })
    }

    api.auth
      .session()
      .then((res) => {
        if (!res.authenticated) redirectToLogin()
        else setChecked(true)
      })
      .catch(redirectToLogin)

    window.addEventListener('dockwatch:unauthorized', redirectToLogin)
    return () => window.removeEventListener('dockwatch:unauthorized', redirectToLogin)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (!checked) return null
  return <>{children}</>
}
