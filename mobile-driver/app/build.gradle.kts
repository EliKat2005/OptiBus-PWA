plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.optibus.driver"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.optibus.driver"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }

    signingConfigs {
        create("release") {
            storeFile = file("../optibus-release-key.jks")
            storePassword = "optibus-f-droid"
            keyAlias = "optibus"
            keyPassword = "optibus-f-droid"
        }
    }

    buildTypes {
        release {
            // DevSecOps: Habilitar ofuscación de código para evitar ingeniería inversa
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.getByName("release")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("com.google.android.material:material:1.10.0")
    
    // OkHttp para conectar con los WebSockets de FastAPI
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
}
