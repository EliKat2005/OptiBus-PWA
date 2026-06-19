package com.optibus.driver

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.content.pm.PackageManager
import android.location.Criteria
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
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.MultipartBody
import java.io.File
import java.io.FileWriter
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.concurrent.thread

class RouteRecorderService : Service(), LocationListener {

    companion object {
        const val CHANNEL_ID = "OptiBusRecorderChannel"
        const val NOTIFICATION_ID = 100
        const val TAG = "OptiBusRecorder"

        const val ACTION_START_RECORDING = "com.optibus.driver.START_RECORDING"
        const val ACTION_PAUSE_RECORDING = "com.optibus.driver.PAUSE_RECORDING"
        const val ACTION_RESUME_RECORDING = "com.optibus.driver.RESUME_RECORDING"
        const val ACTION_STOP_RECORDING = "com.optibus.driver.STOP_RECORDING"
        const val ACTION_ADD_STOP = "com.optibus.driver.ADD_STOP"

        const val BROADCAST_STATS = "com.optibus.driver.RECORDING_STATS"
        const val BROADCAST_EXPORT_DONE = "com.optibus.driver.EXPORT_DONE"
        const val BROADCAST_UPLOAD_STATUS = "com.optibus.driver.UPLOAD_STATUS"

        const val EXTRA_COMPANY = "company"
        const val EXTRA_ROUTE_NAME = "route_name"
        const val EXTRA_TAGS = "tags"
        const val EXTRA_SERVER_URL = "server_url"
        const val EXTRA_API_KEY = "api_key"
        const val EXTRA_BUS_ID = "bus_id"
        const val EXTRA_STOP_NAME = "stop_name"
        const val EXTRA_POINT_COUNT = "point_count"
        const val EXTRA_STOP_COUNT = "stop_count"
        const val EXTRA_DISTANCE_KM = "distance_km"
        const val EXTRA_IS_RECORDING = "is_recording"
        const val EXTRA_IS_PAUSED = "is_paused"
        const val EXTRA_EXPORT_FILES = "export_files"
        const val EXTRA_UPLOAD_MESSAGE = "upload_message"

        const val GPS_INTERVAL_MS = 1000L
        const val GPS_MIN_DISTANCE_M = 0f
    }

    private var company: String = ""
    private var routeName: String = ""
    private var tags: String = ""
    private var serverUrl: String = ""
    private var apiKey: String = ""
    private var busId: String = "Bus-1"

    private val gpsPoints = mutableListOf<GpsPoint>()
    private val stops = mutableListOf<StopPoint>()

    private var totalDistanceMeters = 0.0
    private var lastLocation: Location? = null
    private var isRecording = false
    private var isPaused = false
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
                serverUrl = intent.getStringExtra(EXTRA_SERVER_URL) ?: ""
                apiKey = intent.getStringExtra(EXTRA_API_KEY) ?: ""
                busId = intent.getStringExtra(EXTRA_BUS_ID) ?: "Bus-1"
                startRecording()
            }
            ACTION_PAUSE_RECORDING -> pauseRecording()
            ACTION_RESUME_RECORDING -> resumeRecording()
            ACTION_STOP_RECORDING -> stopAndUpload()
            ACTION_ADD_STOP -> {
                val stopName = intent.getStringExtra(EXTRA_STOP_NAME)
                    ?: "Parada ${stops.size + 1}"
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
        isPaused = false

        val notification = buildNotification(
            "Buscando señal GPS...",
            "Esperando fix inicial (máx 30s)"
        )

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION)
        } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION)
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }

        try {
            locationManager = getSystemService(Context.LOCATION_SERVICE) as LocationManager

            if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION)
                == PackageManager.PERMISSION_GRANTED
            ) {
                val criteria = Criteria().apply {
                    accuracy = Criteria.ACCURACY_FINE
                    powerRequirement = Criteria.POWER_HIGH
                    isAltitudeRequired = true
                }
                val bestProvider = locationManager.getBestProvider(criteria, true)
                    ?: LocationManager.GPS_PROVIDER

                // F3: Registrar listener ANTES de obtener el lastKnownLocation
                locationManager.requestLocationUpdates(
                    LocationManager.GPS_PROVIDER,
                    GPS_INTERVAL_MS,
                    GPS_MIN_DISTANCE_M,
                    this
                )

                if (locationManager.isProviderEnabled(LocationManager.NETWORK_PROVIDER)) {
                    locationManager.requestLocationUpdates(
                        LocationManager.NETWORK_PROVIDER,
                        GPS_INTERVAL_MS * 2,
                        GPS_MIN_DISTANCE_M,
                        this
                    )
                }

                // F3: Esperar primer fix GPS con timeout de 30 segundos
                val lastKnown = locationManager.getLastKnownLocation(bestProvider)
                if (lastKnown != null && lastKnown.time > 0 && (System.currentTimeMillis() - lastKnown.time) < 60_000L) {
                    // LastKnownLocation reciente (< 60s) — lo usamos como punto de partida
                    onLocationChanged(lastKnown)
                    Log.i(TAG, "GPS fix obtenido desde lastKnownLocation: (${lastKnown.latitude}, ${lastKnown.longitude})")
                } else {
                    // No hay lastKnownLocation reciente — esperar el primer fix real
                    val fixStartTime = System.currentTimeMillis()
                    val maxWaitMs = 30_000L // 30 segundos de timeout
                    Log.i(TAG, "Esperando primer fix GPS (timeout ${maxWaitMs / 1000}s)...")
                    
                    while (gpsPoints.isEmpty() && (System.currentTimeMillis() - fixStartTime) < maxWaitMs) {
                        try {
                            Thread.sleep(200)
                        } catch (_: InterruptedException) {
                            break
                        }
                    }
                    
                    if (gpsPoints.isEmpty()) {
                        Log.w(TAG, "Timeout esperando fix GPS. Iniciando grabacion de todas formas.")
                        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
                        nm.notify(NOTIFICATION_ID, buildNotification(
                            "⚠️ Grabando sin GPS fijo: $routeName",
                            "Puntos: 0"
                        ))
                    } else {
                        Log.i(TAG, "Primer fix GPS obtenido tras ${System.currentTimeMillis() - fixStartTime}ms")
                        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
                        nm.notify(NOTIFICATION_ID, buildNotification(
                            "Grabando: $routeName",
                            "Bus: $busId. Puntos: 1"
                        ))
                    }
                }

                Log.i(TAG, "GPS alta precision iniciado: ${GPS_INTERVAL_MS}ms (GPS + Network) - Bus: $busId")
            }
        } catch (e: SecurityException) {
            Log.e(TAG, "Permiso de ubicacion denegado", e)
            stopSelf()
            return
        } catch (e: IllegalArgumentException) {
            Log.e(TAG, "Provider GPS no disponible", e)
        }

        sendStatsBroadcast()
    }

    private fun pauseRecording() {
        if (!isRecording || isPaused) return
        isPaused = true
        try {
            locationManager.removeUpdates(this)
        } catch (e: Exception) {
            Log.w(TAG, "Error pausando GPS: ${e.message}")
        }

        val notification = buildNotification(
            "Grabacion pausada: $routeName",
            "$pointCounter puntos - ${stops.size} paradas"
        )
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.notify(NOTIFICATION_ID, notification)

        if (BuildConfig.DEBUG) Log.i(TAG, "Grabacion pausada: $pointCounter puntos")
        sendStatsBroadcast()
    }

    private fun resumeRecording() {
        if (!isRecording || !isPaused) return
        isPaused = false

        try {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION)
                == PackageManager.PERMISSION_GRANTED
            ) {
                locationManager.requestLocationUpdates(
                    LocationManager.GPS_PROVIDER,
                    GPS_INTERVAL_MS,
                    GPS_MIN_DISTANCE_M,
                    this
                )
                if (BuildConfig.DEBUG) Log.i(TAG, "Grabacion reanudada")
            }
        } catch (e: SecurityException) {
            Log.e(TAG, "Error reanudando GPS", e)
        }

        val notification = buildNotification(
            "Grabando: $routeName",
            "$pointCounter puntos - ${stops.size} paradas"
        )
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.notify(NOTIFICATION_ID, notification)

        sendStatsBroadcast()
    }

    override fun onLocationChanged(location: Location) {
        if (!isRecording || isPaused) return

        val isoTime = SimpleDateFormat(
            "yyyy-MM-dd'T'HH:mm:ss'Z'",
            Locale.US
        ).format(Date(location.time))

        val point = GpsPoint(
            lat = location.latitude,
            lon = location.longitude,
            ele = if (location.hasAltitude()) location.altitude else 0.0,
            time = location.time,
            isoTime = isoTime
        )
        gpsPoints.add(point)
        pointCounter++

        lastLocation?.let { last ->
            val dist = last.distanceTo(location)
            val timeDiff = (location.time - last.time) / 1000.0 // segundos
            val speedMs = if (timeDiff > 0.5) dist / timeDiff else 0.0
            val speedKmh = speedMs * 3.6
            // Ignorar outliers: descartar puntos que implicarían >150 km/h
            if (speedKmh <= 150.0) {
                totalDistanceMeters += dist
            }
        }
        lastLocation = location

        if (pointCounter % 10 == 0) {
            val notification = buildNotification(
                "Grabando: $routeName",
                "$pointCounter pts - ${stops.size} paradas"
            )
            val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            nm.notify(NOTIFICATION_ID, notification)
            sendStatsBroadcast()
        }

        if (BuildConfig.DEBUG) {
            Log.d(TAG, "Punto #$pointCounter: ${location.latitude}, ${location.longitude} (precision: ${location.accuracy}m)")
        }
    }

    fun registerStop(stopName: String) {
        if (!isRecording) return

        val last = lastLocation ?: gpsPoints.lastOrNull()?.let {
            val loc = Location("gps").apply {
                latitude = it.lat
                longitude = it.lon
                altitude = it.ele
            }
            loc
        } ?: run {
            Log.w(TAG, "No hay ubicacion para registrar parada")
            return
        }

        val stop = StopPoint(
            name = stopName,
            lat = last.latitude,
            lon = last.longitude,
            ele = if (last.hasAltitude()) last.altitude else 0.0,
            time = SimpleDateFormat(
                "yyyy-MM-dd'T'HH:mm:ss'Z'",
                Locale.US
            ).format(Date())
        )
        stops.add(stop)

        Log.i(TAG, "Parada registrada: $stopName en (${last.latitude}, ${last.longitude})")
        sendStatsBroadcast()

        // F4: Subir parada individual al backend en tiempo real
        if (serverUrl.isNotBlank()) {
            uploadStopToBackend(stop)
        }
    }

    // F4: Sube una parada individual al backend inmediatamente al registrarla
    private fun uploadStopToBackend(stop: StopPoint) {
        thread(name = "OptiBusUploadStop") {
            try {
                val client = OkHttpClient.Builder()
                    .connectTimeout(10, java.util.concurrent.TimeUnit.SECONDS)
                    .writeTimeout(10, java.util.concurrent.TimeUnit.SECONDS)
                    .readTimeout(10, java.util.concurrent.TimeUnit.SECONDS)
                    .build()

                val url = serverUrl.trimEnd('/') + "/api/stops/record"
                val jsonBody = """
                    {
                        "bus_id": "${escapeJson(busId)}",
                        "stop_name": "${escapeJson(stop.name)}",
                        "lat": ${stop.lat},
                        "lon": ${stop.lon},
                        "elevation": ${stop.ele},
                        "time": "${stop.time}",
                        "route_name": "${escapeJson(routeName)}"
                    }
                """.trimIndent()

                val requestBuilder = Request.Builder()
                    .url(url)
                    .post(RequestBody.create("application/json".toMediaType(), jsonBody))

                if (apiKey.isNotBlank()) {
                    requestBuilder.addHeader("Authorization", "Bearer $apiKey")
                }

                val response = client.newCall(requestBuilder.build()).execute()
                if (response.isSuccessful) {
                    Log.i(TAG, "Parada subida al backend: ${stop.name} (${response.code})")
                } else {
                    Log.w(TAG, "Backend rechazo parada: ${response.code} - ${response.body?.string()}")
                }
            } catch (e: Exception) {
                Log.w(TAG, "Error subiendo parada al backend: ${e.message}")
            }
        }
    }

    private fun stopAndUpload() {
        if (!isRecording) return

        try {
            locationManager.removeUpdates(this)
        } catch (e: Exception) {
            Log.w(TAG, "Error deteniendo GPS: ${e.message}")
        }

        isRecording = false
        isPaused = false
        stopForeground(STOP_FOREGROUND_REMOVE)

        if (gpsPoints.isEmpty()) {
            val intent = Intent(BROADCAST_EXPORT_DONE).apply {
                putExtra(EXTRA_POINT_COUNT, 0)
                putExtra(EXTRA_EXPORT_FILES, "ERROR: No hay puntos GPS grabados")
            }
            sendBroadcast(intent)
            stopSelf()
            return
        }

        val exportedFiles = mutableListOf<String>()

        try {
            val timestamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
            val safeRouteName = routeName.replace(
                Regex("[^a-zA-Z0-9_\\-]"),
                ""
            ).trim()
            val baseName = if (safeRouteName.isNotEmpty()) "${safeRouteName}_$timestamp"
                else "ruta_$timestamp"

            val exportDir = File(cacheDir, "optibus_exports")
            if (!exportDir.exists()) exportDir.mkdirs()

            val gpxFile = File(exportDir, "ruta_${baseName}.gpx")
            writeGpx(gpxFile)
            exportedFiles.add("GPX: ${gpxFile.absolutePath}")

            val stopsJson = buildStopsJson()
            val stopsFile = File(exportDir, "paradas_${baseName}.json")
            stopsFile.writeText(stopsJson)
            exportedFiles.add("Paradas: ${stopsFile.absolutePath}")

            val metaFile = File(exportDir, "metadata_${baseName}.json")
            writeMetadataJson(metaFile)
            exportedFiles.add("Metadatos: ${metaFile.absolutePath}")

            if (serverUrl.isNotBlank()) {
                uploadToBackend(gpxFile, stopsJson)
            }

            val downloadsDir = File(
                Environment.getExternalStoragePublicDirectory(
                    Environment.DIRECTORY_DOWNLOADS
                ),
                "OptiBus"
            )
            if (!downloadsDir.exists()) downloadsDir.mkdirs()
            gpxFile.copyTo(
                File(downloadsDir, "ruta_${baseName}.gpx"),
                overwrite = true
            )
            stopsFile.copyTo(
                File(downloadsDir, "paradas_${baseName}.json"),
                overwrite = true
            )

        } catch (e: Exception) {
            Log.e(TAG, "Error exportando archivos: ${e.message}", e)
            exportedFiles.add("ERROR: ${e.message}")
        }

        val filesStr = exportedFiles.joinToString("\n")
        val doneNotification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Grabacion Finalizada")
            .setContentText("$pointCounter puntos, ${stops.size} paradas (Bus: $busId)")
            .setStyle(NotificationCompat.BigTextStyle().bigText(filesStr))
            .setSmallIcon(android.R.drawable.ic_menu_save)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .build()
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.notify(999, doneNotification)

        val intent = Intent(BROADCAST_EXPORT_DONE).apply {
            putExtra(EXTRA_POINT_COUNT, pointCounter)
            putExtra(EXTRA_STOP_COUNT, stops.size)
            putExtra(EXTRA_EXPORT_FILES, exportedFiles.joinToString("\n"))
        }
        sendBroadcast(intent)

        gpsPoints.clear()
        stops.clear()
        pointCounter = 0
        totalDistanceMeters = 0.0
        lastLocation = null

        stopSelf()
    }

    private fun buildStopsJson(): String {
        val sb = StringBuilder()
        sb.appendLine("[")
        stops.forEachIndexed { index, stop ->
            sb.appendLine("  {")
            sb.append("    \"name\": \"")
            sb.append(escapeJson(stop.name))
            sb.appendLine("\",")
            sb.appendLine("    \"lat\": ${stop.lat},")
            sb.appendLine("    \"lon\": ${stop.lon},")
            sb.appendLine("    \"elevation\": ${stop.ele},")
            sb.append("    \"time\": \"")
            sb.append(stop.time)
            sb.appendLine("\"")
            sb.append("  }")
            if (index < stops.size - 1) sb.append(",")
            sb.appendLine("")
        }
        sb.appendLine("]")
        return sb.toString()
    }

    private fun uploadToBackend(gpxFile: File, stopsJson: String) {
        thread(name = "OptiBusUpload") {
            try {
                val client = OkHttpClient.Builder()
                    .connectTimeout(30, java.util.concurrent.TimeUnit.SECONDS)
                    .writeTimeout(60, java.util.concurrent.TimeUnit.SECONDS)
                    .readTimeout(30, java.util.concurrent.TimeUnit.SECONDS)
                    .build()

                val url = serverUrl.trimEnd('/') + "/api/routes/upload"

                val requestBody = MultipartBody.Builder()
                    .setType(MultipartBody.FORM)
                    .addFormDataPart("route_name", routeName)
                    .addFormDataPart("company", company)
                    .addFormDataPart("tags", tags)
                    .addFormDataPart("stops_json", stopsJson)
                    .addFormDataPart(
                        "gpx_file", gpxFile.name,
                        gpxFile.asRequestBody("application/gpx+xml".toMediaType())
                    )
                    .build()

                val requestBuilder = Request.Builder()
                    .url(url)
                    .post(requestBody)

                if (apiKey.isNotBlank()) {
                    requestBuilder.addHeader("Authorization", "Bearer $apiKey")
                }

                val response = client.newCall(requestBuilder.build()).execute()
                val responseBody = response.body?.string() ?: ""

                if (response.isSuccessful) {
                    Log.i(TAG, "Ruta subida al backend: ${response.code} - $responseBody")
                    val uploadIntent = Intent(BROADCAST_UPLOAD_STATUS).apply {
                        putExtra(
                            EXTRA_UPLOAD_MESSAGE,
                            "Ruta subida exitosamente al servidor"
                        )
                    }
                    sendBroadcast(uploadIntent)
                } else {
                    Log.w(TAG, "Backend rechazo la subida: ${response.code} - $responseBody")
                    val uploadIntent = Intent(BROADCAST_UPLOAD_STATUS).apply {
                        putExtra(
                            EXTRA_UPLOAD_MESSAGE,
                            "Servidor: ${response.code}. Archivos guardados localmente."
                        )
                    }
                    sendBroadcast(uploadIntent)
                }
            } catch (e: Exception) {
                Log.e(TAG, "Error subiendo al backend: ${e.message}", e)
                val uploadIntent = Intent(BROADCAST_UPLOAD_STATUS).apply {
                    putExtra(
                        EXTRA_UPLOAD_MESSAGE,
                        "Error de conexion. Archivos guardados en Descargas/OptiBus/"
                    )
                }
                sendBroadcast(uploadIntent)
            }
        }
    }

    private fun writeGpx(file: File) {
        // F1: Ordenar puntos por timestamp (evita que GPS lento llegue después de Network)
        val sortedPoints = gpsPoints.sortedBy { it.time }
        // F2: Deducir duplicados consecutivos (misma lat+lon dentro de 1m)
        val dedupedPoints = mutableListOf<GpsPoint>()
        var lastDedupLat = Double.NaN
        var lastDedupLon = Double.NaN
        for (point in sortedPoints) {
            if (lastDedupLat.isNaN() || haversineDistance(lastDedupLat, lastDedupLon, point.lat, point.lon) > 1.0) {
                dedupedPoints.add(point)
                lastDedupLat = point.lat
                lastDedupLon = point.lon
            }
        }
        if (dedupedPoints.size < 2) {
            // No deduplicar si eliminamos casi todo; mejor quedarse con sorted
            dedupedPoints.clear()
            dedupedPoints.addAll(sortedPoints)
        }

        FileWriter(file).use { writer ->
            writer.write("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n")
            writer.write("<gpx version=\"1.1\" creator=\"OptiBus Driver App v2.5\"\n")
            writer.write("     xmlns=\"http://www.topografix.com/GPX/1/1\"\n")
            writer.write("     xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\"\n")
            writer.write("     xsi:schemaLocation=\"http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd\">\n")
            writer.write("  <metadata>\n")
            writer.write("    <name>")
            writer.write(escapeXml(routeName))
            writer.write("</name>\n")
            writer.write("    <desc>Compania: ")
            writer.write(escapeXml(company))
            writer.write(" | Bus: $busId | Tags: ")
            writer.write(escapeXml(tags))
            writer.write("</desc>\n")
            writer.write("  </metadata>\n")
            writer.write("  <trk>\n")
            writer.write("    <name>")
            writer.write(escapeXml(routeName))
            writer.write("</name>\n")
            writer.write("    <trkseg>\n")

            for (point in dedupedPoints) {
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

    private fun writeMetadataJson(file: File) {
        val km = String.format("%.3f", totalDistanceMeters / 1000.0)
        val sb = StringBuilder()
        val recordedAt = SimpleDateFormat(
            "yyyy-MM-dd'T'HH:mm:ss'Z'",
            Locale.US
        ).format(Date())

        sb.appendLine("{")
        sb.append("  \"bus_id\": \"")
        sb.append(escapeJson(busId))
        sb.appendLine("\",")
        sb.append("  \"company\": \"")
        sb.append(escapeJson(company))
        sb.appendLine("\",")
        sb.append("  \"route_name\": \"")
        sb.append(escapeJson(routeName))
        sb.appendLine("\",")
        sb.append("  \"tags\": \"")
        sb.append(escapeJson(tags))
        sb.appendLine("\",")
        sb.appendLine("  \"total_points\": $pointCounter,")
        sb.appendLine("  \"total_stops\": ${stops.size},")
        sb.appendLine("  \"distance_km\": $km,")
        sb.appendLine("  \"gps_interval_ms\": $GPS_INTERVAL_MS,")
        sb.append("  \"recorded_at\": \"")
        sb.append(recordedAt)
        sb.appendLine("\"")
        sb.appendLine("}")
        file.writeText(sb.toString())
    }

    // Funciones de escape delegadas a StringEscaper (utilidad centralizada)
    private fun escapeXml(s: String) = StringEscaper.escapeXml(s)
    private fun escapeJson(s: String) = StringEscaper.escapeJson(s)

    private fun sendStatsBroadcast() {
        val distKm = String.format("%.3f", totalDistanceMeters / 1000.0)
        val intent = Intent(BROADCAST_STATS).apply {
            putExtra(EXTRA_POINT_COUNT, pointCounter)
            putExtra(EXTRA_STOP_COUNT, stops.size)
            putExtra(EXTRA_DISTANCE_KM, distKm)
            putExtra(EXTRA_IS_RECORDING, isRecording)
            putExtra(EXTRA_IS_PAUSED, isPaused)
        }
        sendBroadcast(intent)
    }

    private fun buildNotification(title: String, content: String): Notification {
        val pauseIntent = Intent(this, RouteRecorderService::class.java).apply {
            action = if (isPaused) ACTION_RESUME_RECORDING else ACTION_PAUSE_RECORDING
        }
        val pausePendingIntent = PendingIntent.getService(
            this, 1, pauseIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or
                (if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M)
                    PendingIntent.FLAG_IMMUTABLE else 0)
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(title)
            .setContentText(content)
            .setSmallIcon(android.R.drawable.ic_menu_mylocation)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .addAction(
                android.R.drawable.ic_media_pause,
                if (isPaused) "Reanudar" else "Pausar",
                pausePendingIntent
            )
            .build()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Grabacion de Ruta OptiBus",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Canal para grabacion de rutas GPS y paradas"
            }
            val manager = getSystemService(NotificationManager::class.java)
            manager?.createNotificationChannel(channel)
        }
    }

    override fun onDestroy() {
        try {
            locationManager.removeUpdates(this)
        } catch (_: Exception) {}
        super.onDestroy()
    }

    // F1: Distancia Haversine para deduplicación de puntos
    private fun haversineDistance(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
        val R = 6371000.0 // radio Tierra en metros
        val dLat = Math.toRadians(lat2 - lat1)
        val dLon = Math.toRadians(lon2 - lon1)
        val sinDLat = Math.sin(dLat / 2.0)
        val sinDLon = Math.sin(dLon / 2.0)
        val a = sinDLat * sinDLat +
                Math.cos(Math.toRadians(lat1)) * Math.cos(Math.toRadians(lat2)) *
                sinDLon * sinDLon
        return R * 2.0 * Math.atan2(Math.sqrt(a), Math.sqrt(1.0 - a))
    }

    override fun onBind(intent: Intent?): IBinder? = null

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