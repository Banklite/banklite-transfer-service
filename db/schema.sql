-- Esquema de transfer-service (PostgreSQL). Generado a partir de los modelos SQLAlchemy.
-- Tambien se crea solo al arrancar el servicio (Base.metadata.create_all).

CREATE TABLE beneficiario (
	id_beneficiario UUID NOT NULL, 
	id_usuario UUID NOT NULL, 
	nombre VARCHAR(120), 
	cuenta_destino VARCHAR(64) NOT NULL, 
	banco_destino VARCHAR(120), 
	favorito BOOLEAN DEFAULT 'false' NOT NULL, 
	alias VARCHAR(60), 
	telefono VARCHAR(32), 
	PRIMARY KEY (id_beneficiario)
);

CREATE TABLE riel_pago (
	id_riel UUID NOT NULL, 
	tipo VARCHAR(30) NOT NULL, 
	pais VARCHAR(2), 
	activo BOOLEAN NOT NULL, 
	PRIMARY KEY (id_riel), 
	CONSTRAINT ck_riel_tipo CHECK (tipo IN ('ACH','SWIFT','interno'))
);

CREATE TABLE transferencia (
	id_transferencia UUID NOT NULL, 
	id_cuenta_origen UUID NOT NULL, 
	id_beneficiario UUID NOT NULL, 
	id_riel UUID NOT NULL, 
	monto NUMERIC(18, 2) NOT NULL, 
	estado VARCHAR(50) NOT NULL, 
	fecha_solicitud TIMESTAMP WITH TIME ZONE NOT NULL, 
	concepto VARCHAR(255), 
	referencia VARCHAR(100), 
	idempotency_key VARCHAR(100), 
	hash_externo VARCHAR(100), 
	red_externa VARCHAR(50), 
	PRIMARY KEY (id_transferencia), 
	CONSTRAINT ck_transferencia_monto_positivo CHECK (monto > 0), 
	CONSTRAINT ck_transferencia_estado CHECK (estado IN ('pendiente','procesando','completada','rechazada','cancelada','en_revision')), 
	FOREIGN KEY(id_beneficiario) REFERENCES beneficiario (id_beneficiario), 
	FOREIGN KEY(id_riel) REFERENCES riel_pago (id_riel), 
	UNIQUE (idempotency_key)
);
CREATE INDEX idx_transferencia_beneficiario ON transferencia (id_beneficiario);
CREATE INDEX idx_transferencia_estado ON transferencia (estado);
CREATE INDEX idx_transferencia_riel ON transferencia (id_riel);

CREATE TABLE transferencia_programada (
	id_programacion UUID NOT NULL, 
	id_transferencia UUID NOT NULL, 
	frecuencia VARCHAR(32) NOT NULL, 
	proxima_ejecucion TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id_programacion), 
	UNIQUE (id_transferencia), 
	FOREIGN KEY(id_transferencia) REFERENCES transferencia (id_transferencia) ON DELETE CASCADE
);
CREATE INDEX idx_programada_transferencia ON transferencia_programada (id_transferencia);
