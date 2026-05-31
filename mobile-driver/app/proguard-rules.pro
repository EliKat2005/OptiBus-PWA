# OkHttp - Conservar clases necesarias para evitar crashes con R8/ProGuard
-dontwarn okhttp3.internal.platform.**
-dontwarn org.conscrypt.**
-keep class okhttp3.** { *; }
-keep interface okhttp3.** { *; }
-dontwarn okio.**

# Kotlin
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.AnnotationsKt

# JSON (org.json) usado en GPS uploads
-keep class org.json.** { *; }

# OptiBus data classes (usadas via Intent/Broadcast)
-keep class com.optibus.driver.RouteRecorderService$GpsPoint { *; }
-keep class com.optibus.driver.RouteRecorderService$StopPoint { *; }

# StringEscaper utility
-keep class com.optibus.driver.StringEscaper { *; }

# AndroidX Security (EncryptedSharedPreferences)
# Mantener clases de MasterKeys y EncryptedSharedPreferences
-keep class androidx.security.crypto.** { *; }
-dontwarn androidx.security.crypto.**

# BuildConfig (usado para logs condicionales y DEFAULT_SERVER_URL)
-keep class com.optibus.driver.BuildConfig { *; }
