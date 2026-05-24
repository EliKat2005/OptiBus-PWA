package com.optibus.driver

import android.annotation.SuppressLint
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
import android.os.IBinder
import android.util.Log
import okhttp3.*
import org.json.JSONArray
import org.json.JSONObject

class LocationForegroundService : Service(), LocationListener {

    private val CHANNEL_ID = "OptiBusLocationChannel"
    private val NOTIFICATION_ID = 1
    private lateinit var locationManager: LocationManager
    private lateinit var webSocket: WebSocket
    // Optimización: Intervalo inicial a 3 segundos
    private var currentInterval: Long = 3000L

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        initWebSocket()
        startLocationUpdates()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val notification: Notification = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, CHANNEL_ID)
                .setContentTitle("OptiBus Conductor")
                .setContentText("Transmitiendo ubicación en tiempo real...")
                .setSmallIcon(android.R.drawable.ic_menu_mylocation)
                .build()
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this)
                .setContentTitle("OptiBus Conductor")
                .setContentText("Transmitiendo...")
                .setSmallIcon(android.R.drawable.ic_menu_mylocation)
                .build()
        }

        // Especificado con Location en Android 14+
        startForeground(NOTIFICATION_ID, notification)
        return START_STICKY
    }

    @SuppressLint("MissingPermission") // Los permisos ya se pidieron en MainActivity
    private fun startLocationUpdates() {
        locationManager = getSystemService(Context.LOCATION_SERVICE) as LocationManager
        
        locationManager.requestLocationUpdates(
            LocationManager.GPS_PROVIDER,
            currentInterval,
            5f,
            this
        )
    }

    private fun initWebSocket() {
        val client = OkHttpClient()
        // DevSecOps: En producción DEBE ser wss:// (WebSocket Secure).
        // Cambia la IP por tu dominio de producción, ej: "wss://optibus.tu-dominio.com/ws"
        val request = Request.Builder().url("wss://optibus.tu-dominio.com/ws").build()
        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                Log.d("OptiBus", "WebSocket Conectado")
            }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.e("OptiBus", "Fallo WebSocket", t)
            }
        })
    }

    override fun onLocationChanged(location: Location) {
        // Optimización de Batería: Ajuste dinámico de tasa de refresco
        val speedKmh = location.speed * 3.6f
        val desiredInterval = if (speedKmh < 5f) 10000L else 3000L // 10s si está en tráfico/parado, 3s si va libre

        if (desiredInterval != currentInterval) {
            currentInterval = desiredInterval
            Log.d("OptiBus", "Ajustando intervalo GPS a $currentInterval ms (Velocidad: $speedKmh km/h)")
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
        busData.put("id", "Bus-Conductor-1")
        busData.put("line", "Ruta Principal")
        busData.put("lat", location.latitude)
        busData.put("lon", location.longitude)
        
        val busesArray = JSONArray()
        busesArray.put(busData)
        json.put("buses", busesArray)

        // Enviar la coordenada al backend
        webSocket.send(json.toString())
        Log.d("OptiBus", "Enviada coord: ${location.latitude}, ${location.longitude}")
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
        super.onCreate()
        locationManager.removeUpdates(this)
        webSocket.close(1000, "Servicio finalizado")
    }

    override fun onBind(intent: Intent?): IBinder? = null
}
