package com.optibus.driver

/**
 * Utilidades de escape para prevenir inyección en XML y JSON.
 * Centralizadas aquí para evitar duplicación y bugs de encoding.
 *
 * Uso:
 *   StringEscaper.escapeXml("texto con <tags>")
 *   StringEscaper.escapeJson("texto con \"comillas\"")
 */
object StringEscaper {

    fun escapeXml(input: String): String {
        val sb = StringBuilder(input.length + 32)
        for (c in input) {
            when (c) {
                '&' -> sb.append("&").append("amp;")
                '<' -> sb.append("&").append("lt;")
                '>' -> sb.append("&").append("gt;")
                '"' -> sb.append("&").append("quot;")
                '\'' -> sb.append("&").append("apos;")
                else -> sb.append(c)
            }
        }
        return sb.toString()
    }

    fun escapeJson(input: String): String {
        val sb = StringBuilder(input.length + 16)
        for (c in input) {
            when (c) {
                '\\' -> { sb.append("\\\\") }
                '"' -> { sb.append("\\\"") }
                '\n' -> { sb.append("\\n") }
                '\r' -> { sb.append("\\r") }
                '\t' -> { sb.append("\\t") }
                else -> sb.append(c)
            }
        }
        return sb.toString()
    }
}