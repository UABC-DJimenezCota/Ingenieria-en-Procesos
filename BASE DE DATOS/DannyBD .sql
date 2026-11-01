DROP DATABASE IF EXISTS `danny's glassworks`;
CREATE DATABASE `danny's glassworks` CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
USE `danny's glassworks`;

CREATE TABLE `usuarios` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `username` VARCHAR(16) NOT NULL,
  `password` VARCHAR(255) NOT NULL,
  `nombre_completo` VARCHAR(100) DEFAULT NULL,
  `email` VARCHAR(255) DEFAULT NULL,
  `rol` ENUM('admin','empleado','cliente') NOT NULL DEFAULT 'cliente',
  `activo` BOOLEAN NOT NULL DEFAULT TRUE,
  `create_time` TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_usuarios_username` (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `inventario` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `nombre` VARCHAR(100) NOT NULL,
  `categoria` VARCHAR(100) NOT NULL DEFAULT 'Sin clasificar',
  `precio` DECIMAL(10,2) NOT NULL,
  `cantidad` INT NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `recibos` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `folio` VARCHAR(45) DEFAULT NULL,
  `fecha_hora` DATETIME DEFAULT NULL,
  `subtotal` DECIMAL(10,2) DEFAULT NULL,
  `total` DECIMAL(10,2) DEFAULT NULL,
  `metodo_pago` VARCHAR(45) DEFAULT NULL,
  `usuario_id` INT DEFAULT NULL,
  `efectivo_recibido` DECIMAL(10,2) DEFAULT NULL,
  `cambio` DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_recibos_folio` (`folio`),
  KEY `usuario_id` (`usuario_id`),
  CONSTRAINT `recibos_ibfk_1` FOREIGN KEY (`usuario_id`) REFERENCES `usuarios` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `recibo_detalle` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `recibo_id` INT NOT NULL,
  `producto_id` INT NOT NULL,
  `cantidad` INT NOT NULL,
  `precio_unitario` DECIMAL(10,2) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_recibo_producto` (`recibo_id`, `producto_id`),
  KEY `recibo_id` (`recibo_id`),
  KEY `producto_id` (`producto_id`),
  CONSTRAINT `recibo_detalle_ibfk_1` FOREIGN KEY (`recibo_id`) REFERENCES `recibos` (`id`),
  CONSTRAINT `recibo_detalle_ibfk_2` FOREIGN KEY (`producto_id`) REFERENCES `inventario` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `citas` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `cliente_id` INT NOT NULL,
  `fecha_hora` DATETIME NOT NULL,
  `descripcion` TEXT DEFAULT NULL,
  `estado` ENUM('pendiente','confirmada','completada','cancelada') NOT NULL DEFAULT 'pendiente',
  `ubicacion` VARCHAR(255) DEFAULT NULL,
  `presupuesto_estimado` DECIMAL(10,2) DEFAULT 0.00,
  `create_time` TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_cliente` (`cliente_id`),
  CONSTRAINT `fk_citas_cliente` FOREIGN KEY (`cliente_id`) REFERENCES `usuarios` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- Cuentas de ejemplo; cambia las contraseñas para el uso real.
INSERT INTO `usuarios` (`username`, `password`, `nombre_completo`, `email`, `rol`) VALUES
('admin', 'admin', 'Administrador', NULL, 'admin'),
('juan', 'juan123', 'Juan Pérez', NULL, 'empleado'),
('maria', 'maria123', 'María López', NULL, 'empleado'),
('cliente1', 'pass123', 'Carlos Slim', 'carlos@mail.com', 'cliente'),
('cliente2', 'pass456', 'Ana García', 'ana@mail.com', 'cliente');

-- Inventario de ejemplo con categorías para el catálogo de bienvenida.
INSERT INTO `inventario` (`nombre`, `categoria`, `precio`, `cantidad`) VALUES
('Vidrio templado 4mm (m2)', 'Ventana simple', 650.00, 36),
('Vidrio templado 6mm (m2)', 'Ventana simple', 850.00, 25),
('Vidrio templado 8mm (m2)', 'Ventana corrediza horizontal', 1050.00, 18),
('Vidrio templado 10mm (m2)', 'Ventana corrediza vertical', 1280.00, 12),
('Silicón estructural (cartucho)', 'Pared de vidrio', 95.00, 50),
('Perfil de aluminio para ventana (barra 6m)', 'Ventana simple', 220.00, 40),
('Jaladera de acero inoxidable', 'Puertas', 85.00, 45),
('Espejo de baño con luz LED', 'Espejos', 1450.00, 6);

INSERT INTO `recibos` (`folio`, `fecha_hora`, `subtotal`, `total`, `metodo_pago`, `usuario_id`, `efectivo_recibido`, `cambio`) VALUES
('R-20260922171610', '2026-09-22 17:16:10', 650.00, 650.00, 'efectivo', 1, 650.00, 0.00),
('R-20260922204307', '2026-09-22 20:43:07', 850.00, 850.00, 'tarjeta', 2, NULL, 0.00);

INSERT INTO `recibo_detalle` (`recibo_id`, `producto_id`, `cantidad`, `precio_unitario`) VALUES
(1, 1, 1, 650.00),
(2, 2, 1, 850.00);

-- Citas de ejemplo
INSERT INTO `citas` (`cliente_id`, `fecha_hora`, `descripcion`, `estado`, `presupuesto_estimado`) VALUES
(4, '2024-10-25 10:00:00', 'Cotización para cancel de baño en vidrio templado', 'pendiente', 4500.00),
(5, '2024-10-26 15:30:00', 'Medición de ventanal principal en fachada', 'confirmada', 12000.00);

SELECT * FROM `usuarios`;
SELECT * FROM `inventario`;
SELECT * FROM `recibos`;
SELECT * FROM `recibo_detalle`;
SELECT * FROM `citas`;

SELECT
    r.folio, r.fecha_hora, u.nombre_completo AS atendido_por,
    i.nombre AS producto, i.categoria, rd.cantidad, rd.precio_unitario,
    (rd.cantidad * rd.precio_unitario) AS importe,
    r.metodo_pago, r.total, r.efectivo_recibido, r.cambio
FROM recibos r
JOIN usuarios u ON r.usuario_id = u.id
JOIN recibo_detalle rd ON r.id = rd.recibo_id
JOIN inventario i ON rd.producto_id = i.id;