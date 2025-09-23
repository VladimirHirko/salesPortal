// src/main.jsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'

// экраны
import HomeHotelsScreen from './screens/HomeHotelsScreen.jsx'
import TouristsScreen from './screens/TouristsScreen.jsx'
import FamilyScreen from './screens/FamilyScreen.jsx'
import EditBookingScreen from './screens/EditBookingScreen.jsx'

// стили
import './index.css'
import 'react-day-picker/dist/style.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<HomeHotelsScreen />} />
        <Route path="/hotel/:hotelId" element={<TouristsScreen />} />
        <Route path="/family/:famId" element={<FamilyScreen />} />
        <Route path="/bookings/:id/edit" element={<EditBookingScreen />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
)
