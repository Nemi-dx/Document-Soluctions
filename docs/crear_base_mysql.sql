-- Ejecutar una sola vez como administrador de MySQL:
--     mysql -u root -p < docs/crear_base_mysql.sql

CREATE DATABASE IF NOT EXISTS nuam CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Si el usuario "admin" ya existe (el mismo de empleadosProyecto), basta con darle permisos.
-- Si no existe, quita los dos guiones de la línea siguiente:
-- CREATE USER 'admin'@'localhost' IDENTIFIED BY 'mi_clave_123';
GRANT ALL PRIVILEGES ON nuam.* TO 'admin'@'localhost';
-- Django necesita crear una base temporal "test_nuam" para correr las pruebas:
GRANT ALL PRIVILEGES ON `test\_nuam`.* TO 'admin'@'localhost';
FLUSH PRIVILEGES;
