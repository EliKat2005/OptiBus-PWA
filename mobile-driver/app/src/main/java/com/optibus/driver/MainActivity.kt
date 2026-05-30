package com.optibus.driver

import android.Manifest
import android.app.Activity
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.SharedPreferences
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast

class MainActivity : Activity() {

    private val PERMISSION_REQUEST_CODE = 1001
    private lateinit var prefs: SharedPreferences

    // UI - Datos de Ruta
    private lateinit var etCompany: EditText
    private lateinit var etRouteName: EditText
    private lateinit var etTags: EditText

    // UI - Servidor y API Key
    private lateinit var etServerUrl: EditText
    private lateinit var etApiKey: EditText

    // UI - Grabación
    private lateinit var llStats: LinearLayout
    private lateinit var tvPointCount: TextView
    private lateinit var tvStopCount: TextView
    private lateinit var tvDistance: TextView
    private lateinit var tvRecordingStatus: TextView
    private lateinit var tvGpsPrecision: TextView
    private lateinit var btnRecord: Button
    private lateinit var btnPause: Button
    private lateinit var btnResume: Button
    private lateinit var btnStopRecord: Button
    private lateinit var btnAddStop: Button
    private lateinit var tvStopAddedMsg: TextView
    private lateinit var tvUploadStatus: TextView

    // UI - Transmisión
    private lateinit var etServerIp: EditText
    private lateinit var tvServerStatus: TextView
    private lateinit var btnStartTransmission: Button
    private lateinit var btnStopTransmission: Button

    // Estado
    private var isRecording = false
    private var isPaused = false
    private var isTransmitting = false

    // BroadcastReceiver para estadísticas de grabación
    private val statsReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            when (intent?.action) {
                RouteRecorderService.BROADCAST_STATS -> {
                    val points = intent.getIntExtra(RouteRecorderService.EXTRA_POINT_COUNT, 0)
                    val stops = intent.getIntExtra(RouteRecorderService.EXTRA_STOP_COUNT, 0)
                    val distKm = intent.getStringExtra(RouteRecorderService.EXTRA_DISTANCE_KM) ?: "0.0"
                    val recording = intent.getBooleanExtra(RouteRecorderService.EXTRA_IS_RECORDING, false)
                    val paused = intent.getBooleanExtra(RouteRecorderService.EXTRA_IS_PAUSED, false)

                    runOnUiThread {
                        tvPointCount.text = points.toString()
                        tvStopCount.text = stops.toString()
                        tvDistance.text = "${distKm} km"

                        if (recording && !paused) {
                            tvRecordingStatus.text = "⏺️ Grabando... ${points} puntos (GPS 1s)"
                            tvRecordingStatus.setTextColor(android.graphics.Color.parseColor("#D32F2F"))
                            isPaused = false
                            updateRecordingUI(true, false)
                        } else if (recording && paused) {
                            tvRecordingStatus.text = "⏸️ Pausado - ${points} puntos"
                            tvRecordingStatus.setTextColor(android.graphics.Color.parseColor("#FF9800"))
                            isPaused = true
                            updateRecordingUI(true, true)
                        }
                    }
                }
                RouteRecorderService.BROADCAST_EXPORT_DONE -> {
                    val points = intent.getIntExtra(RouteRecorderService.EXTRA_POINT_COUNT, 0)
                    val stops = intent.getIntExtra(RouteRecorderService.EXTRA_STOP_COUNT, 0)
                    val _ = intent.getStringExtra(RouteRecorderService.EXTRA_EXPORT_FILES) ?: ""

                    runOnUiThread {
                        isRecording = false
                        isPaused = false
                        updateRecordingUI(false)
                        tvRecordingStatus.text = "✅ Finalizado: $points pts, $stops paradas"
                        tvRecordingStatus.setTextColor(android.graphics.Color.parseColor("#2E7D32"))

                        Toast.makeText(this@MainActivity,
                            "Archivos guardados en Descargas/OptiBus/",
                            Toast.LENGTH_LONG).show()
                    }
                }
                RouteRecorderService.BROADCAST_UPLOAD_STATUS -> {
                    val message = intent.getStringExtra(RouteRecorderService.EXTRA_UPLOAD_MESSAGE) ?: ""
                    runOnUiThread {
                        tvUploadStatus.text = message
                        tvUploadStatus.visibility = View.VISIBLE
                        tvUploadStatus.postDelayed({
                            tvUploadStatus.visibility = View.GONE
                        }, 5000)
                    }
                }
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        prefs = getSharedPreferences("OptiBusPrefs", Context.MODE_PRIVATE)

        // Binding de vistas
        etCompany = findViewById(R.id.etCompany)
        etRouteName = findViewById(R.id.etRouteName)
        etTags = findViewById(R.id.etTags)
        etServerUrl = findViewById(R.id.etServerUrl)
        etApiKey = findViewById(R.id.etApiKey)

        llStats = findViewById(R.id.llStats)
        tvPointCount = findViewById(R.id.tvPointCount)
        tvStopCount = findViewById(R.id.tvStopCount)
        tvDistance = findViewById(R.id.tvDistance)
        tvRecordingStatus = findViewById(R.id.tvRecordingStatus)
        tvGpsPrecision = findViewById(R.id.tvGpsPrecision)
        btnRecord = findViewById(R.id.btnRecord)
        btnPause = findViewById(R.id.btnPause)
        btnResume = findViewById(R.id.btnResume)
        btnStopRecord = findViewById(R.id.btnStopRecord)
        btnAddStop = findViewById(R.id.btnAddStop)
        tvStopAddedMsg = findViewById(R.id.tvStopAddedMsg)
        tvUploadStatus = findViewById(R.id.tvUploadStatus)

        etServerIp = findViewById(R.id.etServerIp)
        tvServerStatus = findViewById(R.id.tvServerStatus)
        btnStartTransmission = findViewById(R.id.btnStartTransmission)
        btnStopTransmission = findViewById(R.id.btnStopTransmission)

        // Cargar datos guardados
        loadSavedData()

        // Registrar BroadcastReceiver
        val filter = IntentFilter().apply {
            addAction(RouteRecorderService.BROADCAST_STATS)
            addAction(RouteRecorderService.BROADCAST_EXPORT_DONE)
            addAction(RouteRecorderService.BROADCAST_UPLOAD_STATUS)
        }
        registerReceiver(statsReceiver, filter, Context.RECEIVER_NOT_EXPORTED)

        // Mostrar info del GPS
        tvGpsPrecision.text = "GPS: 1s interval • Alta precisión (GPS + Network)"

        // Listeners
        setupListeners()
    }

    private fun loadSavedData() {
        etCompany.setText(prefs.getString("company", ""))
        etRouteName.setText(prefs.getString("route_name", ""))
        etTags.setText(prefs.getString("tags", ""))
        etServerUrl.setText(prefs.getString("server_url", "https://ecae.me"))
        etApiKey.setText(prefs.getString("api_key", ""))
        etServerIp.setText(prefs.getString("server_ip", "192.168.1.12:8000"))
    }

    private fun saveData() {
        prefs.edit()
            .putString("company", etCompany.text.toString().trim())
            .putString("route_name", etRouteName.text.toString().trim())
            .putString("tags", etTags.text.toString().trim())
            .putString("server_url", etServerUrl.text.toString().trim())
            .putString("api_key", etApiKey.text.toString().trim())
            .apply()
    }

    private fun setupListeners() {
        // Guardar al perder foco
        val textWatcher = object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) { saveData() }
        }
        etCompany.addTextChangedListener(textWatcher)
        etRouteName.addTextChangedListener(textWatcher)
        etTags.addTextChangedListener(textWatcher)
        etServerUrl.addTextChangedListener(textWatcher)
        etApiKey.addTextChangedListener(textWatcher)

        // Botón Iniciar Grabación
        btnRecord.setOnClickListener {
            if (checkPermissions()) {
                startRecording()
            } else {
                requestPermissions()
            }
        }

        // Botón Pausar Grabación
        btnPause.setOnClickListener {
            pauseRecording()
        }

        // Botón Reanudar Grabación
        btnResume.setOnClickListener {
            resumeRecording()
        }

        // Botón Detener Grabación
        btnStopRecord.setOnClickListener {
            stopRecording()
        }

        // Botón Registrar Parada
        btnAddStop.setOnClickListener {
            addStop()
        }

        // Botón Iniciar Transmisión
        btnStartTransmission.setOnClickListener {
            if (checkPermissions()) {
                startTransmission()
            } else {
                requestPermissions()
            }
        }

        // Botón Detener Transmisión
        btnStopTransmission.setOnClickListener {
            stopTransmission()
        }
    }

    // ==================== GRABACIÓN DE RUTA ====================

    private fun startRecording() {
        val company = etCompany.text.toString().trim()
        val routeName = etRouteName.text.toString().trim()
        val tags = etTags.text.toString().trim()
        val serverUrl = etServerUrl.text.toString().trim()
        val apiKey = etApiKey.text.toString().trim()

        if (routeName.isEmpty()) {
            Toast.makeText(this, "Ingresa un nombre de ruta antes de grabar", Toast.LENGTH_LONG).show()
            return
        }

        isRecording = true
        isPaused = false
        updateRecordingUI(true, false)

        tvRecordingStatus.text = "⏺️ Iniciando GPS alta precisión..."
        tvRecordingStatus.setTextColor(android.graphics.Color.parseColor("#FF9800"))
        tvStopAddedMsg.visibility = View.GONE
        tvUploadStatus.visibility = View.GONE

        val serviceIntent = Intent(this, RouteRecorderService::class.java).apply {
            action = RouteRecorderService.ACTION_START_RECORDING
            putExtra(RouteRecorderService.EXTRA_COMPANY, company)
            putExtra(RouteRecorderService.EXTRA_ROUTE_NAME, routeName)
            putExtra(RouteRecorderService.EXTRA_TAGS, tags)
            putExtra(RouteRecorderService.EXTRA_SERVER_URL, serverUrl)
            putExtra(RouteRecorderService.EXTRA_API_KEY, apiKey)
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(serviceIntent)
        } else {
            startService(serviceIntent)
        }

        Toast.makeText(this, "Grabación iniciada: $routeName (GPS 1s)", Toast.LENGTH_SHORT).show()
    }

    private fun pauseRecording() {
        if (!isRecording || isPaused) return
        
        val serviceIntent = Intent(this, RouteRecorderService::class.java).apply {
            action = RouteRecorderService.ACTION_PAUSE_RECORDING
        }
        startService(serviceIntent)
        
        isPaused = true
        updateRecordingUI(true, true)
        tvRecordingStatus.text = "⏸️ Grabación pausada"
        tvRecordingStatus.setTextColor(android.graphics.Color.parseColor("#FF9800"))
        Toast.makeText(this, "Grabación pausada", Toast.LENGTH_SHORT).show()
    }

    private fun resumeRecording() {
        if (!isRecording || !isPaused) return
        
        val serviceIntent = Intent(this, RouteRecorderService::class.java).apply {
            action = RouteRecorderService.ACTION_RESUME_RECORDING
        }
        startService(serviceIntent)
        
        isPaused = false
        updateRecordingUI(true, false)
        tvRecordingStatus.text = "⏺️ Grabación reanudada"
        tvRecordingStatus.setTextColor(android.graphics.Color.parseColor("#D32F2F"))
        Toast.makeText(this, "Grabación reanudada", Toast.LENGTH_SHORT).show()
    }

    private fun stopRecording() {
        val serviceIntent = Intent(this, RouteRecorderService::class.java).apply {
            action = RouteRecorderService.ACTION_STOP_RECORDING
        }
        startService(serviceIntent)

        tvRecordingStatus.text = "⏳ Finalizando y subiendo datos..."
        tvRecordingStatus.setTextColor(android.graphics.Color.parseColor("#FF9800"))
        btnStopRecord.isEnabled = false
        btnPause.isEnabled = false
        btnResume.isEnabled = false
    }

    private fun addStop() {
        if (!isRecording) {
            Toast.makeText(this, "Inicia una grabación primero", Toast.LENGTH_SHORT).show()
            return
        }

        val stopCount = tvStopCount.text.toString().toIntOrNull() ?: 0
        val stopName = "Parada ${stopCount + 1}"

        val serviceIntent = Intent(this, RouteRecorderService::class.java).apply {
            action = RouteRecorderService.ACTION_ADD_STOP
            putExtra(RouteRecorderService.EXTRA_STOP_NAME, stopName)
        }
        startService(serviceIntent)

        // Mostrar confirmación breve
        tvStopAddedMsg.text = "✅ $stopName registrada"
        tvStopAddedMsg.visibility = View.VISIBLE
        tvStopAddedMsg.postDelayed({
            tvStopAddedMsg.visibility = View.GONE
        }, 2500)

        Toast.makeText(this, "$stopName registrada", Toast.LENGTH_SHORT).show()
    }

    private fun updateRecordingUI(recording: Boolean, paused: Boolean = false) {
        if (recording) {
            llStats.visibility = View.VISIBLE
            btnRecord.visibility = View.GONE
            btnStopRecord.visibility = View.VISIBLE
            btnStopRecord.isEnabled = true
            btnAddStop.visibility = View.VISIBLE

            if (paused) {
                btnPause.visibility = View.GONE
                btnResume.visibility = View.VISIBLE
            } else {
                btnPause.visibility = View.VISIBLE
                btnResume.visibility = View.GONE
            }

            // Deshabilitar campos de datos de ruta durante la grabación
            etCompany.isEnabled = false
            etRouteName.isEnabled = false
            etTags.isEnabled = false
            etServerUrl.isEnabled = false
            etApiKey.isEnabled = false
        } else {
            llStats.visibility = View.GONE
            btnRecord.visibility = View.VISIBLE
            btnPause.visibility = View.GONE
            btnResume.visibility = View.GONE
            btnStopRecord.visibility = View.GONE
            btnAddStop.visibility = View.GONE
            tvStopAddedMsg.visibility = View.GONE

            // Re-habilitar campos
            etCompany.isEnabled = true
            etRouteName.isEnabled = true
            etTags.isEnabled = true
            etServerUrl.isEnabled = true
            etApiKey.isEnabled = true
        }
    }

    // ==================== TRANSMISIÓN AL SERVIDOR ====================

    private fun startTransmission() {
        val ip = etServerIp.text.toString().trim()
        prefs.edit().putString("server_ip", ip).apply()

        val serviceIntent = Intent(this, LocationForegroundService::class.java)
        serviceIntent.putExtra("SERVER_IP", ip)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(serviceIntent)
        } else {
            startService(serviceIntent)
        }

        isTransmitting = true
        tvServerStatus.text = "Servidor: Conectado a $ip"
        tvServerStatus.setTextColor(android.graphics.Color.parseColor("#2E7D32"))
        tvServerStatus.setBackgroundColor(android.graphics.Color.parseColor("#E8F5E9"))

        btnStartTransmission.visibility = View.GONE
        btnStopTransmission.visibility = View.VISIBLE
        etServerIp.isEnabled = false

        Toast.makeText(this, "Transmisión iniciada a $ip", Toast.LENGTH_SHORT).show()
    }

    private fun stopTransmission() {
        val serviceIntent = Intent(this, LocationForegroundService::class.java)
        stopService(serviceIntent)

        isTransmitting = false
        tvServerStatus.text = "Servidor: Desconectado"
        tvServerStatus.setTextColor(android.graphics.Color.parseColor("#D32F2F"))
        tvServerStatus.setBackgroundColor(android.graphics.Color.parseColor("#FFEBEE"))

        btnStartTransmission.visibility = View.VISIBLE
        btnStopTransmission.visibility = View.GONE
        etServerIp.isEnabled = true

        Toast.makeText(this, "Transmisión detenida", Toast.LENGTH_SHORT).show()
    }

    // ==================== PERMISOS ====================

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
        // Android 11+: pedir MANAGE_EXTERNAL_STORAGE si es necesario
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            permissions.add(Manifest.permission.WRITE_EXTERNAL_STORAGE)
            permissions.add(Manifest.permission.READ_EXTERNAL_STORAGE)
        }
        requestPermissions(permissions.toTypedArray(), PERMISSION_REQUEST_CODE)
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == PERMISSION_REQUEST_CODE &&
            grantResults.isNotEmpty() &&
            grantResults[0] == PackageManager.PERMISSION_GRANTED
        ) {
            Toast.makeText(this, "Permisos otorgados. Ya puedes iniciar.", Toast.LENGTH_SHORT).show()
        } else {
            Toast.makeText(this, "Se requieren permisos de GPS y almacenamiento", Toast.LENGTH_LONG).show()
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        try {
            unregisterReceiver(statsReceiver)
        } catch (e: Exception) {
            // Receiver ya no registrado
        }
    }
}