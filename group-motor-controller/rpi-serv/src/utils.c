#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>
#include "utils.h"

void debug_printf(const char* format, ...) {
    int debug = env_or("DEBUG", "0")[0] != '\0' && env_or("DEBUG", "0")[0] != '0';
    if (!debug) {
        return;
    }
    va_list args;
    va_start(args, format);
    vprintf(format, args);
    va_end(args);
    return;
}

// Valeur d'une variable d'environnement, ou valeur par defaut si absente
const char *env_or(const char *name, const char *def) {
    const char *v = getenv(name);
    return (v != NULL && v[0] != '\0') ? v : def;
}