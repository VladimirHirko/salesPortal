// src/main.jsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import HomeHotelsScreen from './screens/HomeHotelsScreen.jsx'
import TouristsScreen from './screens/TouristsScreen.jsx'

const router = createBrowserRouter([
  { path: '/', element: <HomeHotelsScreen/> },
  { path: '/hotel/:hotelId', element: <TouristsScreen/> },
])

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>
)
