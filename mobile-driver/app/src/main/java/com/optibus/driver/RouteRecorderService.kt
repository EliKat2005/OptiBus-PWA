package com.optibus.driver

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import java.io.File
import java.io.FileWriter
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * OptiBus RouteRecorderService v2.0
 * Foreground Service para grabación de rutas GPS y registro de paradas.
 * Exporta archivos .gpx y .json compatibles directamente con backend/ingest_gpx.py e ingest_stops.py
 */
class RouteRecorderService : Service(), LocationListener {

    companion object {
        const val CHANNEL_ID = "OptiBusRecorderChannel"
        const val NOTIFICATION_ID = 100
        const val TAG = "OptiBusRecorder"

        // Acciones de Intent
        const val ACTION_START_RECORDING = "com.optibus.driver.START_RECORDING"
        const val ACTION_STOP_RECORDING = "com.optibus.driver.STOP_RECORDING"
        const val ACTION_ADD_STOP = "com.optibus.driver.ADD_STOP"

        // Broadcast de estadísticas para la Activity
        const val BROADCAST_STATS = "com.optibus.driver.RECORDING_STATS"
        const val BROADCAST_EXPORT_DONE = "com.optibus.driver.EXPORT_DONE"

        // Extras
        const val EXTRA_COMPANY = "company"
        const val EXTRA_ROUTE_NAME = "route_name"
        const val EXTRA_TAGS = "tags"
        const val EXTRA_STOP_NAME = "stop_name"
        const val EXTRA_POINT_COUNT = "point_count"
        const val EXTRA_STOP_COUNT = "stop_count"
        const val EXTRA_DISTANCE_KM = "distance_km"
        const val EXTRA_IS_RECORDING = "is_recording"
        const val EXTRA_EXPORT_FILES = "export_files"

        const val GPS_INTERVAL_MS = 3000L // 3 segundos
        const val GPS_MIN_DISTANCE_M = 0f
    }

    // Datos de la ruta
    private var company: String = ""
    private var routeName: String = ""
    private var tags: String = ""

    // Colección de puntos GPS (lon, lat, elevación, timestamp)
    private val gpsPoints = mutableListOf<GpsPoint>()
    // Colección de paradas registradas
    private val stops = mutableListOf<StopPoint>()

    private var totalDistanceMeters = 0.0
    private var lastLocation: Location? = null
    private var isRecording = false
    private var pointCounter = 0

    private lateinit var locationManager: LocationManager

    data class GpsPoint(
        val lat: Double,
        val lon: Double,
        val ele: Double,
        val time: Long,
        val isoTime: String
    )

    data class StopPoint(
        val name: String,
        val lat: Double,
        val lon: Double,
        val ele: Double,
        val time: String
    )

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START_RECORDING -> {
                company = intent.getStringExtra(EXTRA_COMPANY) ?: ""
                routeName = intent.getStringExtra(EXTRA_ROUTE_NAME) ?: "Ruta sin nombre"
                tags = intent.getStringExtra(EXTRA_TAGS) ?: ""
                startRecording()
            }
            ACTION_STOP_RECORDING -> {
                stopAndExport()
            }
            ACTION_ADD_STOP -> {
                val stopName = intent.getStringExtra(EXTRA_STOP_NAME) ?: "Parada ${stops.size + 1}"
                registerStop(stopName)
            }
        }
        return START_STICKY
    }

    private fun startRecording() {
        if (isRecording) return
        
        gpsPoints.clear()
        stops.clear()
        totalDistanceMeters = 0.0
        lastLocation = null
        pointCounter = 0
        isRecording = true

        // Notificación foreground
        val notification = buildNotification("Grabando: $routeName", "Compañía: $company")
        
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION)
        } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION)
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }

        // Iniciar GPS
        try {
            locationManager = getSystemService(Context.LOCATION_SERVICE) as LocationManager
            
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) 
                == PackageManager.PERMISSION_GRANTED) {
                
                locationManager.requestLocationUpdates(
                    LocationManager.GPS_PROVIDER,
                    GPS_INTERVAL_MS,
                    GPS_MIN_DISTANCE_M,
                    this
                )

                // Primer punto con última ubicación conocida
                locationManager.getLastKnownLocation(LocationManager.GPS_PROVIDER)?.let {
                    onLocationChanged(it)
                }
                
                Log.i(TAG, "Grabación iniciada: $routeName (${company})")
            }
        } catch (e: SecurityException) {
            Log.e(TAG, "Permiso de ubicación denegado", e)
            stopSelf()
            return
        } catch (e: IllegalArgumentException) {
            Log.e(TAG, "GPS Provider no disponible", e)
        }

        sendStatsBroadcast()
    }

    override fun onLocationChanged(location: Location) {
        if (!isRecording) return

        val isoTime = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).format(Date(location.time))
        
        val point = GpsPoint(
            lat = location.latitude,
            lon = location.longitude,
            ele = if (location.hasAltitude()) location.altitude else 0.0,
            time = location.time,
            isoTime = isoTime
        )
        gpsPoints.add(point)
        pointCounter++

        // Calcular distancia acumulada
        lastLocation?.let { last ->
            totalDistanceMeters += last.distanceTo(location)
        }
        lastLocation = location

        // Enviar broadcast cada 5 puntos para no saturar
        if (pointCounter % 5 == 0) {
            sendStatsBroadcast()
        }

        Log.d(TAG, "Punto #$pointCounter: ${location.latitude}, ${location.longitude}")
    }

    fun registerStop(stopName: String) {
        if (!isRecording) return

        // Usar la última ubicación conocida
        val last = lastLocation ?: gpsPoints.lastOrNull()?.let {
            val loc = Location("gps").apply {
                latitude = it.lat
                longitude = it.lon
                altitude = it.ele
            }
            loc
        } ?: run {
            Log.w(TAG, "No hay ubicación para registrar parada")
            return
        }
        
        val stop = StopPoint(
            name = stopName,
            lat = last.latitude,
            lon = last.longitude,
            ele = if (last.hasAltitude()) last.altitude else 0.0,
            time = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).format(Date())
        )
        stops.add(stop)
        
        Log.i(TAG, "Parada registrada: $stopName en (${last.latitude}, ${last.longitude})")
        sendStatsBroadcast()
    }

    private fun stopAndExport() {
        if (!isRecording) return
        
        // Detener GPS
        try {
            locationManager.removeUpdates(this)
        } catch (e: Exception) {
            Log.w(TAG, "Error deteniendo GPS: ${e.message}")
        }
        
        isRecording = false
        stopForeground(STOP_FOREGROUND_REMOVE)

        val exportedFiles = mutableListOf<String>()

        try {
            val timestamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
            val safeRouteName = routeName.replace(Regex("[^a-zA-Z0-9áéíóúÁÉÍÓÚñÑüÜ _\\-]"), "").trim()
            val baseName = if (safeRouteName.isNotEmpty()) "${safeRouteName}_$timestamp" else "ruta_$timestamp"

            // Crear directorio de exportación
            val exportDir = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), "OptiBus")
            if (!exportDir.exists()) {
                exportDir.mkdirs()
            }

            // 1. Exportar GPX (formato compatible con ingest_gpx.py)
            val gpxFile = File(exportDir, "ruta_${baseName}.gpx")
            writeGpx(gpxFile)
            exportedFiles.add("GPX: ${gpxFile.absolutePath}")
            Log.i(TAG, "GPX exportado: ${gpxFile.absolutePath}")

            // 2. Exportar paradas JSON (formato compatible con ingest_stops.py)
            val stopsFile = File(exportDir, "paradas_${baseName}.json")
            writeStopsJson(stopsFile)
            exportedFiles.add("Paradas: ${stopsFile.absolutePath}")
            Log.i(TAG, "Paradas JSON exportado: ${stopsFile.absolutePath}")

            // 3. Exportar metadatos JSON (referencia humana)
            val metaFile = File(exportDir, "metadata_${baseName}.json")
            writeMetadataJson(metaFile)
            exportedFiles.add("Metadatos: ${metaFile.absolutePath}")
            Log.i(TAG, "Metadatos exportado: ${metaFile.absolutePath}")

        } catch (e: Exception) {
            Log.e(TAG, "Error exportando archivos: ${e.message}", e)
            exportedFiles.add("ERROR: ${e.message}")
        }

        // Notificar exportación completada
        val filesStr = exportedFiles.joinToString("\n")
        val doneNotification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Exportación Completada")
            .setContentText("$pointCounter puntos, ${stops.size} paradas")
            .setStyle(NotificationCompat.BigTextStyle().bigText(filesStr))
            .setSmallIcon(android.R.drawable.ic_menu_save)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .build()
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.notify(999, doneNotification)

        // Enviar broadcast a la Activity
        val intent = Intent(BROADCAST_EXPORT_DONE).apply {
            putExtra(EXTRA_POINT_COUNT, pointCounter)
            putExtra(EXTRA_STOP_COUNT, stops.size)
            putExtra(EXTRA_EXPORT_FILES, exportedFiles.joinToString("\n"))
        }
        sendBroadcast(intent)

        // Limpiar datos
        gpsPoints.clear()
        stops.clear()
        pointCounter = 0
        totalDistanceMeters = 0.0
        lastLocation = null

        stopSelf()
    }

    private fun writeGpx(file: File) {
        FileWriter(file).use { writer ->
            writer.write("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n")
            writer.write("<gpx version=\"1.1\" creator=\"OptiBus Driver App v2.0\"\n")
            writer.write("     xmlns=\"http://www.topografix.com/GPX/1/1\"\n")
            writer.write("     xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\"\n")
            writer.write("     xsi:schemaLocation=\"http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd\">\n")
            writer.write("  <metadata>\n")
            writer.write("    <name>${escapeXml(routeName)}</name>\n")
            writer.write("    <desc>Compañía: ${escapeXml(company)} | Tags: ${escapeXml(tags)}</desc>\n")
            writer.write("  </metadata>\n")
            writer.write("  <trk>\n")
            writer.write("    <name>${escapeXml(routeName)}</name>\n")
            writer.write("    <trkseg>\n")

            for (point in gpsPoints) {
                writer.write("      <trkpt lat=\"${point.lat}\" lon=\"${point.lon}\">\n")
                if (point.ele != 0.0) {
                    writer.write("        <ele>${point.ele}</ele>\n")
                }
                writer.write("        <time>${point.isoTime}</time>\n")
                writer.write("      </trkpt>\n")
            }

            writer.write("    </trkseg>\n")
            writer.write("  </trk>\n")
            writer.write("</gpx>\n")
        }
    }

    private fun writeStopsJson(file: File) {
        val sb = StringBuilder()
        sb.appendLine("[")
        stops.forEachIndexed { index, stop ->
            sb.appendLine("  {")
            sb.appendLine("    \"name\": \"${escapeJson(stop.name)}\",")
            sb.appendLine("    \"lat\": ${stop.lat},")
            sb.appendLine("    \"lon\": ${stop.lon},")
            sb.appendLine("    \"elevation\": ${stop.ele},")
            sb.appendLine("    \"time\": \"${stop.time}\",")
            sb.appendLine("    \"route_name\": \"${escapeJson(routeName)}\",")
            sb.appendLine("    \"company\": \"${escapeJson(company)}\",")
            sb.appendLine("    \"tags\": \"${escapeJson(tags)}\"")
            sb.append("  }")
            if (index < stops.size - 1) sb.append(",")
            sb.appendLine("")
        }
        sb.appendLine("]")
        file.writeText(sb.toString())
    }

    private fun writeMetadataJson(file: File) {
        val km = String.format("%.3f", totalDistanceMeters / 1000.0)
        val sb = StringBuilder()
        sb.appendLine("{")
        sb.appendLine("  \"company\": \"${escapeJson(company)}\",")
        sb.appendLine("  \"route_name\": \"${escapeJson(routeName)}\",")
        sb.appendLine("  \"tags\": \"${escapeJson(tags)}\",")
        sb.appendLine("  \"total_points\": $pointCounter,")
        sb.appendLine("  \"total_stops\": ${stops.size},")
        sb.appendLine("  \"distance_km\": $km,")
        sb.appendLine("  \"recorded_at\": \"${SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).format(Date())}\"")
        sb.appendLine("}")
        file.writeText(sb.toString())
    }

    private fun escapeXml(s: String): String = s
        .replace("&", "&")
        .replace("<", "<")
        .replace(">", ">")
        .replace("\"", """)
        .replace("'", "'")

    private fun escapeJson(s: String): String = s
        .replace("\\", "\\\\")
        .replace("\"", "\\\"")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")

    private fun sendStatsBroadcast() {
        val distKm = String.format("%.3f", totalDistanceMeters / 1000.0)
        val intent = Intent(BROADCAST_STATS).apply {
            putExtra(EXTRA_POINT_COUNT, pointCounter)
            putExtra(EXTRA_STOP_COUNT, stops.size)
            putExtra(EXTRA_DISTANCE_KM, distKm)
            putExtra(EXTRA_IS_RECORDING, isRecording)
        }
        sendBroadcast(intent)
    }

    private fun buildNotification(title: String, content: String): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(title)
            .setContentText(content)
            .setSmallIcon(android.R.drawable.ic_menu_mylocation)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Grabación de Ruta OptiBus",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Canal para grabación de rutas GPS y paradas"
            }
            val manager = getSystemService(NotificationManager::class.java)
            manager?.createNotificationChannel(channel)
        }
    }

    override fun onDestroy() {
        try {
            locationManager.removeUpdates(this)
        } catch (e: Exception) {}
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    // Métodos requeridos por LocationListener
    @Deprecated("Use onLocationChanged(Location) instead")
    override fun onLocationChanged(locations: MutableList<Location>) {
        for (location in locations) {
            onLocationChanged(location)
        }
    }

    override fun onFlushComplete(requestCode: Int) {}
    override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}
    override fun onProviderEnabled(provider: String) {}
    override fun onProviderDisabled(provider: String) {}
}