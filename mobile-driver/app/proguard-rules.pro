# OkHttp - Conservar clases necesarias para evitar crashes con R8/ProGuard
-dontwarn okhttp3.internal.platform.**
-dontwarn org.conscrypt.**
-keep class okhttp3.** { *; }
-keep interface okhttp3.** { *; }
-dontwarn okio.**

# Kotlin
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.AnnotationsKt
