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
