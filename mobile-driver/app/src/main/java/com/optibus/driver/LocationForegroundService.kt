package com.optibus.driver

import android.annotation.SuppressLint
import android.content.pm.ServiceInfo
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.Log
import okhttp3.*
import okhttp3.CertificatePinner
import org.json.JSONArray
import org.json.JSONObject

class LocationForegroundService : Service(), LocationListener {

    private val CHANNEL_ID = "OptiBusLocationChannel"
    private val NOTIFICATION_ID = 1
    private lateinit var locationManager: LocationManager
    private var webSocket: WebSocket? = null
    private var currentInterval: Long = 3000L
    private var busId = "Bus-Conductor-1"
    private var serverIp = "192.168.1.12:8000"

    // DevSecOps: Reconexión WebSocket con backoff exponencial
    private val handler = Handler(Looper.getMainLooper())
    private var reconnectDelay = 1000L
    private val maxReconnectDelay = 30_000L
    private var reconnectAttempts = 0

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        startLocationUpdates()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        serverIp = intent?.getStringExtra("SERVER_IP") ?: "192.168.1.12:8000"
        busId = intent?.getStringExtra("BUS_ID") ?: "Bus-Conductor-1"

        // Reiniciamos websocket si cambia / arranca
        reconnectAttempts = 0
        reconnectDelay = 1000L
        initWebSocket(serverIp)

        val notification: Notification = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, CHANNEL_ID)
                .setContentTitle("OptiBus Conductor")
                .setContentText("Transmitiendo a $serverIp (Bus: $busId)")
                .setSmallIcon(android.R.drawable.ic_menu_mylocation)
                .build()
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this)
                .setContentTitle("OptiBus Conductor")
                .setContentText("Transmitiendo... ($serverIp)")
                .setSmallIcon(android.R.drawable.ic_menu_mylocation)
                .build()
        }

        // Especificado con Location en Android 14+
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION
            )
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
        return START_STICKY
    }

    @SuppressLint("MissingPermission")
    private fun startLocationUpdates() {
        try {
            locationManager = getSystemService(Context.LOCATION_SERVICE) as LocationManager
            locationManager.requestLocationUpdates(
                LocationManager.GPS_PROVIDER,
                currentInterval,
                0f,
                this
            )
            
            // Forzar un primer envío inmediato con la última ubicación conocida
            locationManager.getLastKnownLocation(LocationManager.GPS_PROVIDER)?.let {
                onLocationChanged(it)
            }
        } catch (e: SecurityException) {
            Log.e("OptiBus", "Fallo al solicitar ubicación: Permiso denegado.", e)
        } catch (e: IllegalArgumentException) {
            Log.e("OptiBus", "Fallo al solicitar ubicación: GPS Provider no encontrado.", e)
        }
    }

    private fun initWebSocket(serverIp: String) {
        // Cerrar previo si existe
        webSocket?.close(1000, "Reconectando")
        
        val prefs = getSharedPreferences("OptiBusPrefs", Context.MODE_PRIVATE)
        
        // DevSecOps: Forzar wss:// en producción, ws:// solo para IPs locales
        val isLocalIp = serverIp.matches(
            Regex("^(10\\.|172\\.(1[6-9]|2[0-9]|3[0-1])\\.|192\\.168\\.|127\\.|localhost).*")
        )
        val protocol = if (isLocalIp) "ws" else "wss"
        
        val url = when {
            serverIp.startsWith("ws://") || serverIp.startsWith("wss://") ->
                if (isLocalIp) serverIp else serverIp.replace("ws://", "wss://")
            else -> "$protocol://$serverIp/ws"
        }
        
        if (BuildConfig.DEBUG) {
            Log.i("OptiBus", "Conectando WebSocket a $url (local=$isLocalIp, protocol=$protocol)")
        }
        
        // DevSecOps: OkHttpClient con Certificate Pinning para conexiones no locales
        val clientBuilder = OkHttpClient.Builder()
        
        if (!isLocalIp) {
            // Extraer hostname para certificate pinning
            val hostname = serverIp
                .replace("ws://", "").replace("wss://", "")
                .substringBefore(":").substringBefore("/")
            
            // Certificate pinning: solo si el usuario ha configurado pins en SharedPreferences
            val pinSha256 = prefs.getString("cert_pin_sha256", "")?.trim()
            if (!pinSha256.isNullOrEmpty()) {
                val certificatePinner = CertificatePinner.Builder()
                    .add(hostname, "sha256/$pinSha256")
                    .build()
                clientBuilder.certificatePinner(certificatePinner)
                Log.i("OptiBus", "Certificate pinning HABILITADO para $hostname")
            } else {
                Log.w("OptiBus", "Certificate pinning DESHABILITADO. Configura cert_pin_sha256 en SharedPreferences para activar.")
            }
        }
        
        val client = clientBuilder.build()
        
        val requestBuilder = Request.Builder().url(url)
        
        // Agregar API Key si está configurada en SharedPreferences
        val apiKey = prefs.getString("api_key", "")?.trim()
        if (!apiKey.isNullOrEmpty()) {
            requestBuilder.addHeader("Authorization", "Bearer $apiKey")
        }
        
        val request = requestBuilder.build()
        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                Log.i("OptiBus", "WebSocket Conectado a $url")
                // Resetear backoff al conectar exitosamente
                reconnectAttempts = 0
                reconnectDelay = 1000L
            }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.e("OptiBus", "Fallo WebSocket en $url (intento #$reconnectAttempts): ${t.message}")
                scheduleReconnect()
            }
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                Log.i("OptiBus", "WebSocket cerrado (code=$code): $reason")
                if (code != 1000) {
                    scheduleReconnect()
                }
            }
        })
    }

    // DevSecOps: Reconexión con backoff exponencial
    private fun scheduleReconnect() {
        reconnectAttempts++
        if (reconnectAttempts > 1) {
            reconnectDelay = (reconnectDelay * 2).coerceAtMost(maxReconnectDelay)
        }
        Log.i("OptiBus", "Reconexión WS en ${reconnectDelay}ms (intento #$reconnectAttempts)")
        handler.postDelayed({
            initWebSocket(serverIp)
        }, reconnectDelay)
    }

    override fun onLocationChanged(location: Location) {
        // Optimización de Batería: Ajuste dinámico de tasa de refresco
        val speedKmh = location.speed * 3.6f
        val desiredInterval = if (speedKmh < 5f) 10000L else 3000L

        if (desiredInterval != currentInterval) {
            currentInterval = desiredInterval
            if (BuildConfig.DEBUG) {
                Log.d("OptiBus", "Ajustando intervalo GPS a $currentInterval ms (Velocidad: $speedKmh km/h)")
            }
            try {
                locationManager.removeUpdates(this)
                startLocationUpdates()
            } catch (e: SecurityException) {
                Log.e("OptiBus", "Fallo al refrescar intervalo GPS", e)
            }
        }

        // Estructura JSON idéntica a lo que espera la PWA
        val json = JSONObject()
        json.put("type", "bus_positions")
        
        val busData = JSONObject()
        busData.put("id", busId)
        busData.put("line", "Ruta Principal")
        busData.put("lat", location.latitude)
        busData.put("lon", location.longitude)
        
        val busesArray = JSONArray()
        busesArray.put(busData)
        json.put("buses", busesArray)

        // Enviar la coordenada al backend si el WS está instanciado
        webSocket?.send(json.toString())
        if (BuildConfig.DEBUG) {
            Log.d("OptiBus", "Enviada coord: ${location.latitude}, ${location.longitude} (Bus: $busId)")
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Canal de Rastreo OptiBus",
                NotificationManager.IMPORTANCE_LOW
            )
            val manager = getSystemService(NotificationManager::class.java)
            manager?.createNotificationChannel(channel)
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        handler.removeCallbacksAndMessages(null)
        locationManager.removeUpdates(this)
        webSocket?.close(1000, "Servicio finalizado")
    }

    override fun onBind(intent: Intent?): IBinder? = null
}