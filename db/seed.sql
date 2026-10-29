-- Datos de ejemplo de transfer-service. Ejecutar despues de schema.sql.
INSERT INTO riel_pago (id_riel, tipo, pais, activo) VALUES
 ('00000000-0000-0000-0000-000000000101','interno',NULL,true),
 ('00000000-0000-0000-0000-000000000102','ACH','CO',true),
 ('00000000-0000-0000-0000-000000000103','SWIFT',NULL,true)
ON CONFLICT DO NOTHING;
-- El riel 'stellar-testnet' lo agrega el servicio al arrancar (amplia el CHECK ck_riel_tipo).
INSERT INTO beneficiario (id_beneficiario, id_usuario, nombre, cuenta_destino, banco_destino, favorito, alias) VALUES
 ('40000000-0000-0000-0000-000000000001','11111111-1111-1111-1111-111111111111','Luis Demo','aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2','BankLite',true,'Luis')
ON CONFLICT DO NOTHING;
INSERT INTO transferencia (id_transferencia, id_cuenta_origen, id_beneficiario, id_riel, monto, estado, fecha_solicitud, concepto, referencia) VALUES
 ('50000000-0000-0000-0000-000000000001','aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1','40000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000101',50000,'completada',now(),'Ejemplo de transferencia','SEED-TRF-0001')
ON CONFLICT DO NOTHING;
INSERT INTO transferencia_programada (id_programacion, id_transferencia, frecuencia, proxima_ejecucion) VALUES
 ('60000000-0000-0000-0000-000000000001','50000000-0000-0000-0000-000000000001','mensual',now() + interval '30 days')
ON CONFLICT DO NOTHING;
