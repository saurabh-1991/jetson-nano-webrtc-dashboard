import React from 'react'
import './ToggleSwitch.css'

const ToggleSwitch = ({ isOn, handleToggle, label, disabled = false }) => {
  return (
    <div className="switch-container">
      {label && <span className="switch-label">{label}</span>}
      <label className="toggle-switch">
        <input
          type="checkbox"
          checked={isOn}
          onChange={handleToggle}
          disabled={disabled}
        />
        <span className="slider round"></span>
      </label>
    </div>
  )
}

export default ToggleSwitch
