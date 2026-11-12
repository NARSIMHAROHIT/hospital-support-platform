
import { Navigate, Route, Routes } from 'react-router-dom'

import ProtectedRoute from './components/ProtectedRoute'
import PatientLayout from './layouts/PatientLayout'

import Login from './pages/Login'
import Signup from './pages/Signup'
import Dashboard from './pages/Dashboard'
import Doctors from './pages/Doctors'
import Appointments from './pages/Appointments'
import SupportTickets from './pages/SupportTickets'
import Profile from './pages/Profile'
import RescheduleAppointment from './pages/RescheduleAppointment'
import MedicalRecords from './pages/MedicalRecords'
import AIChat from './pages/AIChat'
import DoctorDashboard from './pages/DoctorDashboard'
import NurseDashboard from './pages/NurseDashboard'


function AdminDashboard() {
  return (
    <main style={{ padding: 32 }}>
      <h1>Hospital Admin Portal</h1>
      <p>
        Administrator dashboard and doctor management
        are coming next.
      </p>
    </main>
  )
}

export default function App() {
  return (
    <Routes>
      {/* Public routes */}
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />

      {/* Patient-only routes */}
      <Route
        element={
          <ProtectedRoute allowedRoles={['patient']} />
        }
      >
        <Route element={<PatientLayout />}>
          <Route
            path="/dashboard"
            element={<Dashboard />}
          />

          <Route
            path="/doctors"
            element={<Doctors />}
          />

          <Route
            path="/appointments"
            element={<Appointments />}
          />

          <Route
            path="/support"
            element={<SupportTickets />}
          />

          <Route
            path="/medical-records"
            element={<MedicalRecords />}
          />
          <Route
              path="/ai-assistant"
              element={<AIChat />}
            />
                      <Route
            path="/profile"
            element={<Profile />}
          />

          <Route
            path="/appointments/:appointmentId/reschedule"
            element={<RescheduleAppointment />}
          />
        </Route>
      </Route>

      {/* Doctor-only routes */}
      <Route
        element={
          <ProtectedRoute allowedRoles={['doctor']} />
        }
      >
        <Route
          path="/doctor/dashboard"
          element={<DoctorDashboard />}
        />
      </Route>

      {/* Nurse-only routes */}
      <Route
        element={
          <ProtectedRoute allowedRoles={['nurse']} />
        }
      >
        <Route
          path="/nurse/dashboard"
          element={<NurseDashboard />}
        />
      </Route>

      {/* Admin-only routes */}
      <Route
        element={
          <ProtectedRoute allowedRoles={['admin']} />
        }
      >
        <Route
          path="/admin/dashboard"
          element={<AdminDashboard />}
        />
      </Route>

      {/* Default routes */}
      <Route
        path="/"
        element={<Navigate to="/login" replace />}
      />

      <Route
        path="*"
        element={<Navigate to="/login" replace />}
      />

    </Routes>
  )
}
