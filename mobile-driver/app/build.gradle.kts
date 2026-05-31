import java.io.FileInputStream
import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// DevSecOps: Cargar credenciales del keystore desde archivo externo
// Crea keystore.properties en la raíz de mobile-driver/ con:
//   KEYSTORE_FILE=../optibus-release-key.jks
//   KEYSTORE_PASSWORD=tu_password
//   KEY_ALIAS=optibus
//   KEY_PASSWORD=tu_password
val keystorePropertiesFile = rootProject.file("keystore.properties")
val keystoreProperties = Properties()
if (keystorePropertiesFile.exists()) {
    keystoreProperties.load(FileInputStream(keystorePropertiesFile))
}

android {
    namespace = "com.optibus.driver"
    compileSdk = 35

    buildFeatures {
        buildConfig = true
    }

    defaultConfig {
        applicationId = "com.optibus.driver"
        minSdk = 26
        targetSdk = 35
        versionCode = 4
        versionName = "2.2"

        // DevSecOps: Variable de build para controlar logs solo en debug
        buildConfigField("String", "DEFAULT_SERVER_URL", "\"https://ecae.me\"")
    }

    signingConfigs {
        create("release") {
            if (keystorePropertiesFile.exists()) {
                storeFile = file(keystoreProperties["KEYSTORE_FILE"] as String)
                storePassword = keystoreProperties["KEYSTORE_PASSWORD"] as String
                keyAlias = keystoreProperties["KEY_ALIAS"] as String
                keyPassword = keystoreProperties["KEY_PASSWORD"] as String
            }
        }
    }

    buildTypes {
        release {
            // DevSecOps: Habilitar ofuscación de código para evitar ingeniería inversa
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            // Solo firmar si el keystore está configurado
            if (keystorePropertiesFile.exists()) {
                signingConfig = signingConfigs.getByName("release")
            }
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
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")

    // OkHttp para conectar con los WebSockets de FastAPI
    implementation("com.squareup.okhttp3:okhttp:4.12.0")

    // DevSecOps: EncryptedSharedPreferences para proteger API Key y credenciales
    implementation("androidx.security:security-crypto:1.1.0-alpha06")
}
