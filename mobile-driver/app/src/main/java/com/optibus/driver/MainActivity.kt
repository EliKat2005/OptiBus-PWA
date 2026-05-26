package com.optibus.driver

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.content.pm.PackageManager
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import android.os.Build

class MainActivity : Activity() {

    private val PERMISSION_REQUEST_CODE = 1001
    private lateinit var prefs: SharedPreferences
    
    private lateinit var etServerIp: EditText
    private lateinit var tvStatus: TextView
    private lateinit var btnStart: Button
    private lateinit var btnStop: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        prefs = getSharedPreferences("OptiBusPrefs", Context.MODE_PRIVATE)

        etServerIp = findViewById(R.id.etServerIp)
        tvStatus = findViewById(R.id.tvStatus)
        btnStart = findViewById(R.id.btnStart)
        btnStop = findViewById(R.id.btnStop)

        // Cargar IP guardado
        val savedIp = prefs.getString("server_ip", "192.168.1.12:8000")
        etServerIp.setText(savedIp)

        btnStart.setOnClickListener {
            if (checkPermissions()) {
                startLocationService()
            } else {
                requestPermissions()
            }
        }
        
        btnStop.setOnClickListener {
            stopLocationService()
        }
    }

    private fun checkPermissions(): Boolean {
        return checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
    }

    private fun requestPermissions() {
        val permissions = mutableListOf(
            Manifest.permission.ACCESS_FINE_LOCATION,
            Manifest.permission.ACCESS_COARSE_LOCATION
        )
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            permissions.add(Manifest.permission.POST_NOTIFICATIONS)
        }
        requestPermissions(permissions.toTypedArray(), PERMISSION_REQUEST_CODE)
    }

    override fun onRequestPermissionsResult(
        requestCode: Int, permissions: Array<out String>, grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == PERMISSION_REQUEST_CODE && grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            startLocationService()
        } else {
            Toast.makeText(this, "Se requieren permisos de GPS para transmitir", Toast.LENGTH_LONG).show()
        }
    }

    private fun startLocationService() {
        // Guardar la IP configurada
        val ip = etServerIp.text.toString().trim()
        prefs.edit().putString("server_ip", ip).apply()

        val serviceIntent = Intent(this, LocationForegroundService::class.java)
        serviceIntent.putExtra("SERVER_IP", ip)
        
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(serviceIntent)
        } else {
            startService(serviceIntent)
        }
        
        tvStatus.text = "Estado: Transmitiendo"
        tvStatus.setTextColor(android.graphics.Color.parseColor("#4CAF50"))
        btnStart.visibility = View.GONE
        btnStop.visibility = View.VISIBLE
        etServerIp.isEnabled = false
        
        Toast.makeText(this, "Transmisión iniciada", Toast.LENGTH_SHORT).show()
    }
    
    private fun stopLocationService() {
        val serviceIntent = Intent(this, LocationForegroundService::class.java)
        stopService(serviceIntent)
        
        tvStatus.text = "Estado: Desconectado"
        tvStatus.setTextColor(android.graphics.Color.parseColor("#D32F2F"))
        btnStart.visibility = View.VISIBLE
        btnStop.visibility = View.GONE
        etServerIp.isEnabled = true
        
        Toast.makeText(this, "Transmisión detenida", Toast.LENGTH_SHORT).show()
    }
}
