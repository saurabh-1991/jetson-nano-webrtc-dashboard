import React, { useEffect, useState } from 'react'
import VideoStream from './components/VideoStream'
import GPIOControls from './components/GPIOControls'
import DeviceStatus from './components/DeviceStatus'
import SensorDataSection from './components/SensorDataSection'
import ExperimentControl from './components/ExperimentControl'
import ToggleSwitch from './components/ToggleSwitch'
import TroubleshootLogs from './components/TroubleshootLogs'
import { cameraAPI, systemAPI } from './services/api'
import './App.css'

function App() {
  const [showLogs, setShowLogs] = useState(false)
  const [softwareVersion, setSoftwareVersion] = useState('unknown')
  const [enabledCameraIds, setEnabledCameraIds] = useState(['cam1'])
  const [activeTab, setActiveTab] = useState('dashboard')

  useEffect(() => {
    let mounted = true

    const refreshSoftwareVersion = async () => {
      try {
        const [infoResponse, cameraResponse] = await Promise.allSettled([
          systemAPI.getInfo(),
          cameraAPI.getEnabled(),
        ])

        const label = infoResponse.status === 'fulfilled'
          ? infoResponse?.value?.data?.software?.label
          : null

        const enabledIdsFromCameraApi = cameraResponse.status === 'fulfilled'
          ? cameraResponse?.value?.data?.enabled_camera_ids
          : null
        const enabledIdsFromSystemInfo = infoResponse.status === 'fulfilled'
          ? infoResponse?.value?.data?.camera?.enabled_camera_ids
          : null
        const enabledIds = Array.isArray(enabledIdsFromCameraApi) && enabledIdsFromCameraApi.length > 0
          ? enabledIdsFromCameraApi
          : enabledIdsFromSystemInfo

        if (mounted && label) {
          setSoftwareVersion(label)
        }

        if (mounted && Array.isArray(enabledIds) && enabledIds.length > 0) {
          setEnabledCameraIds(enabledIds)
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
        <div className="top-tabs">
          <button
            type="button"
            className={`tab-btn ${activeTab === 'dashboard' ? 'active' : ''}`}
            onClick={() => setActiveTab('dashboard')}
          >
            Live Operations
          </button>
          <button
            type="button"
            className={`tab-btn ${activeTab === 'experiments' ? 'active' : ''}`}
            onClick={() => setActiveTab('experiments')}
          >
            Experiment Monitor
          </button>
        </div>

        {activeTab === 'dashboard' ? (
          <>
            <div className="operations-cockpit-grid">
              <section className="dashboard-section camera1-panel">
                <h2>Camera 1 (Main)</h2>
                {enabledCameraIds.includes('cam1') ? (
                  <VideoStream
                    cameraId="cam1"
                    startLabel="Start Cam 1"
                    stopLabel="Stop Cam 1"
                  />
                ) : (
                  <div className="camera-unavailable">Cam 1 is disabled in backend configuration.</div>
                )}
              </section>

              <section className="dashboard-section camera2-panel">
                <h2>Camera 2 (IR)</h2>
                {enabledCameraIds.includes('cam2') ? (
                  <VideoStream
                    cameraId="cam2"
                    startLabel="Start Cam 2"
                    stopLabel="Stop Cam 2"
                    forceMjpeg
                  />
                ) : (
                  <div className="camera-unavailable">Cam 2 is disabled in backend configuration.</div>
                )}
              </section>

              <section className="dashboard-section cockpit-experiment-rail">
                <ExperimentControl
                  title="Experiment Control"
                  showHistory={false}
                  showPlayback={false}
                  compact
                />
                <button
                  type="button"
                  className="open-monitor-btn"
                  onClick={() => setActiveTab('experiments')}
                >
                  Open Experiment Monitor
                </button>
              </section>
            </div>

            <div className="dashboard-grid dashboard-grid-secondary">

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
          </>
        ) : (
          <div className="experiments-tab-layout">
            <section className="dashboard-section experiment-panel">
              <ExperimentControl />
            </section>
          </div>
        )}
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
