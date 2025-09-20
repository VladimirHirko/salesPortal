// src/main.jsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import { RouterProvider, createBrowserRouter } from 'react-router-dom'

// ГЛОБАЛЬНЫЕ СТИЛИ — однажды, в точке входа
import './index.css'
import 'react-day-picker/dist/style.css'

import HomeHotelsScreen from './screens/HomeHotelsScreen.jsx'
import TouristsScreen from './screens/TouristsScreen.jsx'
import FamilyScreen from './screens/FamilyScreen.jsx'


const router = createBrowserRouter([
  { path: '/', element: <HomeHotelsScreen/> },
  { path: '/hotel/:hotelId', element: <TouristsScreen/> },
  { path: '/family/:famId', element: <FamilyScreen/> },
])

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>
)
