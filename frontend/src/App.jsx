import React from 'react'
import VideoStream from './components/VideoStream'
import GPIOControls from './components/GPIOControls'
import DeviceStatus from './components/DeviceStatus'
import SensorDataSection from './components/SensorDataSection'
import './App.css'

function App() {
  return (
    <div className="app-container">
      <header className="app-header">
        <div className="header-content">
          <h1>Dashboard</h1>
          <p className="subtitle">Real-time Video Streaming & GPIO Control</p>
        </div>
      </header>

      <main className="app-main">
        <div className="dashboard-grid">
          {/* Video Stream Section */}
          <section className="dashboard-section camera-panel">
            <h2>Live Camera Feed</h2>
            <VideoStream />
          </section>

          {/* GPIO Controls Section */}
          <section className="dashboard-section controls-panel">
            <GPIOControls />
          </section>

          {/* Device Status Section */}
          <section className="dashboard-section status-panel">
            <DeviceStatus />
          </section>

          {/* Sensor Data + Graph Section */}
          <section className="dashboard-section full-width">
            <SensorDataSection />
          </section>
        </div>
      </main>

      <footer className="app-footer">
        <p>Dashboard v1.0.0 | Powered by FastAPI + React</p>
      </footer>
    </div>
  )
}

export default App
