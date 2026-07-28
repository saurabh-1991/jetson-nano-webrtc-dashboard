import React, { useEffect, useState } from 'react'
import CameraWindow from './components/CameraWindow'
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
  const [enabledCameraIds, setEnabledCameraIds] = useState(['cam1', 'cam2'])
  const [autoLiveSignal, setAutoLiveSignal] = useState(0)
  const cam1Enabled = enabledCameraIds.includes('cam1')
  const cam2Enabled = enabledCameraIds.includes('cam2')
  const singleCameraMode = (cam1Enabled && !cam2Enabled) || (!cam1Enabled && cam2Enabled)

  const handleRunStarted = () => {
    setAutoLiveSignal((prev) => prev + 1)
  }

  useEffect(() => {
    let mounted = true
    let refreshTimer = null

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
    refreshTimer = setInterval(() => {
      refreshSoftwareVersion()
    }, 15000)

    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        refreshSoftwareVersion()
      }
    }

    document.addEventListener('visibilitychange', onVisibilityChange)

    return () => {
      mounted = false
      if (refreshTimer) {
        clearInterval(refreshTimer)
      }
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
          <section className={`dashboard-section camera1-panel ${singleCameraMode ? 'camera-single' : ''}`}>
            <CameraWindow
              cameraId="cam1"
              title="Camera 1 (Main)"
              enabled={cam1Enabled}
              startLabel="Start Cam 1"
              stopLabel="Stop Cam 1"
              autoLiveSignal={autoLiveSignal}
              autoConnectDelayMs={0}
            />
          </section>

          <section className={`dashboard-section camera2-panel ${singleCameraMode ? 'camera-single' : ''}`}>
            <CameraWindow
              cameraId="cam2"
              title="Camera 2 (IR)"
              enabled={cam2Enabled}
              startLabel="Start Cam 2"
              stopLabel="Stop Cam 2"
              forceMjpeg
              autoLiveSignal={autoLiveSignal}
              autoConnectDelayMs={650}
            />
          </section>

          <section className="dashboard-section experiment-panel full-width">
            <ExperimentControl
              title="Experiment Control"
              showHistory
              showPlayback={false}
              compact
              onRunStarted={handleRunStarted}
            />
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
