import React, { useEffect, useState } from 'react'
import VideoStream from './components/VideoStream'
import GPIOControls from './components/GPIOControls'
import DeviceStatus from './components/DeviceStatus'
import SensorDataSection from './components/SensorDataSection'
import ToggleSwitch from './components/ToggleSwitch'
import TroubleshootLogs from './components/TroubleshootLogs'
import { systemAPI } from './services/api'
import './App.css'

function App() {
  const [showLogs, setShowLogs] = useState(false)
  const [softwareVersion, setSoftwareVersion] = useState('unknown')

  useEffect(() => {
    let mounted = true

    const refreshSoftwareVersion = async () => {
      try {
        const response = await systemAPI.getInfo()
        const label = response?.data?.software?.label
        if (mounted && label) {
          setSoftwareVersion(label)
        }
      } catch (_e) {
        // no-op: keep last known value
      }
    }

    refreshSoftwareVersion()

    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        refreshSoftwareVersion()
      }
    }

    document.addEventListener('visibilitychange', onVisibilityChange)

    return () => {
      mounted = false
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [])

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
            <h2>Live Camera Feeds</h2>
            <div className="camera-grid">
              <div className="camera-tile">
                <h3>Camera 1 (Main)</h3>
                <VideoStream
                  cameraId="cam1"
                  startLabel="Start Cam 1"
                  stopLabel="Stop Cam 1"
                />
              </div>
              <div className="camera-tile">
                <h3>Camera 2 (IR)</h3>
                <VideoStream
                  cameraId="cam2"
                  startLabel="Start Cam 2"
                  stopLabel="Stop Cam 2"
                  forceMjpeg
                />
              </div>
            </div>
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

        <div className="logs-toggle-row">
          <ToggleSwitch
            label="Show Troubleshooting Logs"
            isOn={showLogs}
            handleToggle={() => setShowLogs((prev) => !prev)}
          />
        </div>

        <TroubleshootLogs enabled={showLogs} />
      </main>

      <footer className="app-footer">
        <p>
          Dashboard v1.2.0 | Branch: <span className="footer-branch">{softwareVersion}</span> | Powered by FastAPI + React
        </p>
      </footer>
    </div>
  )
}

export default App
