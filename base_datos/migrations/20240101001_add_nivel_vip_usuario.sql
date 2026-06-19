-- Migration: 20240101001_add_nivel_vip_usuario
-- Description: Agrega columna nivel_vip a usuarios para clasificación premium.
--              Ejemplo de migración evolutiva sin romper integridad referencial.
-- ──────────────────────────────────────────────────────────

ALTER TABLE produccion.usuarios
ADD COLUMN IF NOT EXISTS nivel_vip VARCHAR(20)
    CHECK (nivel_vip IN ('standard','silver','gold','platinum') OR nivel_vip IS NULL);

COMMENT ON COLUMN produccion.usuarios.nivel_vip IS
    'Clasificación VIP derivada de score_rentabilidad. NULL hasta que se ejecute el recalculo.';

-- Poblar con valor derivado de score_rentabilidad existente
UPDATE produccion.usuarios
SET nivel_vip = CASE
    WHEN score_rentabilidad >= 75 THEN 'platinum'
    WHEN score_rentabilidad >= 50 THEN 'gold'
    WHEN score_rentabilidad >= 25 THEN 'silver'
    ELSE 'standard'
END
WHERE nivel_vip IS NULL;

CREATE INDEX IF NOT EXISTS idx_usuarios_nivel_vip
    ON produccion.usuarios (nivel_vip)
    WHERE nivel_vip IN ('gold','platinum');
