
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import './Signup.css'

async function postJson(path, payload) {
  const response = await fetch(path, {
    method: 'POST',
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })

  const data = await response.json().catch(() => ({}))

  if (!response.ok) {
    const detail = data.detail
    const message = typeof detail === 'string'
      ? detail
      : Array.isArray(detail)
        ? detail.map(item => item.msg).join(', ')
        : 'Something went wrong. Please try again.'

    throw new Error(message)
  }

  return data
}

export default function Signup() {
  const navigate = useNavigate()

  const [step, setStep] = useState('register')
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [otp, setOtp] = useState('')

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  async function register(event) {
    event.preventDefault()
    setError('')
    setMessage('')

    if (password !== confirmPassword) {
      setError('Passwords do not match.')
      return
    }

    if (password.length < 12) {
      setError('Password must be at least 12 characters.')
      return
    }

    setBusy(true)

    try {
      const data = await postJson('/auth/register/start', {
        full_name: fullName.trim(),
        email: email.trim().toLowerCase(),
        password,
      })

      setPassword('')
      setConfirmPassword('')
      setStep('verify')
      setMessage(data.message)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function verify(event) {
    event.preventDefault()
    setError('')
    setMessage('')

    if (!/^\d{6}$/.test(otp)) {
      setError('Enter the six-digit verification code.')
      return
    }

    setBusy(true)

    try {
      await postJson('/auth/register/verify', {
        email: email.trim().toLowerCase(),
        otp,
      })

      setOtp('')
      navigate('/login', {
        replace: true,
        state: {
          signupSuccess: true,
        },
      })
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function resend() {
    setBusy(true)
    setError('')
    setMessage('')

    try {
      const data = await postJson('/auth/register/resend', {
        email: email.trim().toLowerCase(),
      })

      setMessage(data.message)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="signup-page">
      <section className="signup-card">
        <div className="signup-brand">
          <span className="signup-brand-icon">+</span>
          <div>
            <h1>Hospital Portal</h1>
            <p>Secure patient registration</p>
          </div>
        </div>

        <div className="signup-progress">
          <span className="signup-progress-active">
            1. Account
          </span>
          <span className={
            step === 'verify' ? 'signup-progress-active' : ''
          }>
            2. Verify Email
          </span>
        </div>

        {step === 'register' ? (
          <>
            <h2>Create your account</h2>
            <p className="signup-subtitle">
              Register as a patient to manage appointments
              and access your patient portal.
            </p>

            <form onSubmit={register}>
              <label htmlFor="signup-name">Full Name</label>
              <input
                id="signup-name"
                type="text"
                autoComplete="name"
                required
                minLength={2}
                maxLength={100}
                value={fullName}
                onChange={event =>
                  setFullName(event.target.value)
                }
                placeholder="Enter full name"
              />

              <label htmlFor="signup-email">Email</label>
              <input
                id="signup-email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={event =>
                  setEmail(event.target.value)
                }
                placeholder="name@example.com"
              />

              <label htmlFor="signup-password">Password</label>
              <input
                id="signup-password"
                type="password"
                autoComplete="new-password"
                minLength={12}
                maxLength={128}
                required
                value={password}
                onChange={event =>
                  setPassword(event.target.value)
                }
                placeholder="At least 12 characters"
              />

              <label htmlFor="signup-confirm">
                Confirm Password
              </label>
              <input
                id="signup-confirm"
                type="password"
                autoComplete="new-password"
                required
                value={confirmPassword}
                onChange={event =>
                  setConfirmPassword(event.target.value)
                }
                placeholder="Re-enter password"
              />

              <button type="submit" disabled={busy}>
                {busy ? 'Sending code...' : 'Continue'}
              </button>
            </form>
          </>
        ) : (
          <>
            <h2>Verify your email</h2>

            <p className="signup-subtitle">
              Enter the six-digit verification code for{' '}
              <strong>{email}</strong>.
              The code expires in five minutes.
            </p>

            <form onSubmit={verify}>
              <label htmlFor="signup-otp">
                Verification Code
              </label>
              <input
                id="signup-otp"
                className="signup-otp"
                type="text"
                inputMode="numeric"
                pattern="[0-9]{6}"
                maxLength={6}
                autoComplete="one-time-code"
                value={otp}
                onChange={event =>
                  setOtp(
                    event.target.value
                      .replace(/\D/g, '')
                      .slice(0, 6)
                  )
                }
                placeholder="000000"
                required
              />

              <button type="submit" disabled={busy}>
                {busy ? 'Verifying...' : 'Verify & Create Account'}
              </button>
            </form>

            <button
              type="button"
              className="signup-secondary-button"
              onClick={resend}
              disabled={busy}
            >
              Resend Verification Code
            </button>

            <button
              type="button"
              className="signup-text-button"
              onClick={() => {
                setOtp('')
                setStep('register')
              }}
              disabled={busy}
            >
              Edit account details
            </button>
          </>
        )}

        {error && (
          <p className="signup-error" role="alert">
            {error}
          </p>
        )}

        {message && (
          <p className="signup-message" role="status">
            {message}
          </p>
        )}

        <p className="signup-footer">
          Already have an account?{' '}
          <Link to="/login">Sign In</Link>
        </p>

        <small>
          Educational demonstration — use fictional data only.
        </small>
      </section>
    </main>
  )
}
