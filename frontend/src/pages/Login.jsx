
import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { authApi } from '../api/client'
import { homeForRole } from '../components/ProtectedRoute'

export default function Login() {
  const navigate = useNavigate()
  const location = useLocation()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const signupSuccess = location.state?.signupSuccess === true

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    setLoading(true)

    try {
      await authApi.login(email.trim(), password)

      const response = await fetch('/auth/me', {
        credentials: 'include',
      })

      if (!response.ok) {
        throw new Error('Unable to verify account')
      }

      const user = await response.json()
      const destination = homeForRole(user.role)

      if (destination === '/login') {
        throw new Error('Unsupported account role')
      }

      setPassword('')
      navigate(destination, {
        replace: true,
        state: null,
      })
    } catch (err) {
      console.error('Login failed:', err)

      setError(
        typeof err.message === 'string'
          ? err.message
          : 'Sign in failed. Please try again.'
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="login-page">
      <form className="login-card" onSubmit={handleSubmit}>
        <h1>Hospital Portal</h1>

        <p>
          Sign in as a patient, doctor, or administrator.
        </p>

        {signupSuccess && (
          <p
            role="status"
            style={{
              padding: '12px',
              borderRadius: '8px',
              background: '#dcfce7',
              color: '#166534',
              marginBottom: '18px',
            }}
          >
            Your email has been verified successfully.
            Your patient account is ready. Please sign in.
          </p>
        )}

        <label htmlFor="email">Email Address</label>
        <input
          id="email"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="name@example.com"
          required
          autoComplete="username"
        />

        <label htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          placeholder="Enter your password"
          required
          autoComplete="current-password"
        />

        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}

        <button type="submit" disabled={loading}>
          {loading ? 'Signing in...' : 'Sign In'}
        </button>

        <p
          style={{
            textAlign: 'center',
            marginTop: '20px',
            marginBottom: '16px',
          }}
        >
          New patient?{' '}
          <Link
            to="/signup"
            style={{
              color: '#2563eb',
              fontWeight: 600,
              textDecoration: 'none',
            }}
          >
            Create Account
          </Link>
        </p>

        <small>
         THE HOSPITAL PORTAL IS FOR PATIENTS, DOCTORS, AND ADMINISTRATORS ONLY
        </small>
      </form>
    </main>
  )
}
