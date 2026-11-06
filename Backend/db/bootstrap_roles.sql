-- =============================================================================
-- OPS-02 · bootstrap_roles.sql — roles de PostgreSQL para Neon (dev y prod)
-- =============================================================================
-- Crea UNA SOLA VEZ por proyecto/base los dos roles de servicio y deja listos el
-- esquema `app` y los privilegios por defecto (SRS §12.8, mínimo privilegio):
--
--   svc_migrator  Dueño de los objetos. Lo usa SOLO Alembic (CI / servicio migrador)
--                 mediante DATABASE_URL_MIGRATOR. No debe existir en el servidor de la API.
--   svc_app       Rol de la API en ejecución (DATABASE_URL). Solo SELECT, INSERT y UPDATE
--                 sobre las tablas del esquema `app`; nada de DDL, DELETE ni TRUNCATE.
--
-- Uso (conectado como el propietario inicial: `neondb_owner` en Neon, `postgres` en local):
--
--   psql "$OWNER_URL" \
--        -v migrator_password="$SVC_MIGRATOR_PASSWORD" \
--        -v app_password="$SVC_APP_PASSWORD" \
--        -f backend/db/bootstrap_roles.sql
--
-- · Las contraseñas llegan por variables de psql (`-v`): NUNCA se escriben en este archivo.
-- · Necesitan 32 o más caracteres aleatorios (el script se detiene si son más cortas).
-- · Es idempotente: se puede repetir para rotar contraseñas o reparar privilegios.
-- · Los GRANT de cada tabla NO viven aquí: las tablas nuevas heredan los privilegios por
--   defecto de abajo y las políticas RLS irán en migraciones de Alembic (SRS §12.8).
-- =============================================================================

\set ON_ERROR_STOP on
\set QUIET on

-- 0. Contraseñas obligatorias y de largo suficiente -----------------------------
\if :{?migrator_password}
\else
  \echo 'falta -v migrator_password=...'
  DO $$ BEGIN RAISE EXCEPTION 'bootstrap_roles: falta -v migrator_password=...'; END $$;
\endif
\if :{?app_password}
\else
  \echo 'falta -v app_password=...'
  DO $$ BEGIN RAISE EXCEPTION 'bootstrap_roles: falta -v app_password=...'; END $$;
\endif

SELECT (length(:'migrator_password') >= 32 AND length(:'app_password') >= 32) AS passwords_ok \gset
\if :passwords_ok
\else
  \echo 'las contraseñas deben tener 32 o más caracteres'
  DO $$ BEGIN RAISE EXCEPTION 'bootstrap_roles: las contraseñas deben tener 32 o más caracteres'; END $$;
\endif

-- 1. Roles (idempotente) ---------------------------------------------------------
-- NOINHERIT NOCREATEDB NOCREATEROLE y sin SUPERUSER/REPLICATION/BYPASSRLS (SRS §12.8).
-- format(%L) escapa la contraseña como literal; \gexec ejecuta cada fila resultante.
SELECT format(
         'CREATE ROLE %I LOGIN NOINHERIT NOCREATEDB NOCREATEROLE NOSUPERUSER NOREPLICATION NOBYPASSRLS PASSWORD %L',
         r.rol, r.pwd)
  FROM (VALUES ('svc_migrator', :'migrator_password'),
               ('svc_app',      :'app_password')) AS r(rol, pwd)
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r.rol)
\gexec

-- Rotación: repetir el script cambia la contraseña de ambos roles.
SELECT format('ALTER ROLE %I WITH PASSWORD %L', r.rol, r.pwd)
  FROM (VALUES ('svc_migrator', :'migrator_password'),
               ('svc_app',      :'app_password')) AS r(rol, pwd)
\gexec

-- 2. Parámetros por rol ------------------------------------------------------------
-- search_path = app: las tablas, los tipos enum y la tabla alembic_version se crean y se
-- resuelven en `app` sin tocar `public` (que queda sin privilegios, ver paso 4).
ALTER ROLE svc_migrator SET search_path = app;
ALTER ROLE svc_migrator SET statement_timeout = '120s';                 -- las migraciones pueden tardar
ALTER ROLE svc_migrator SET idle_in_transaction_session_timeout = '30s';

ALTER ROLE svc_app SET search_path = app;
ALTER ROLE svc_app SET statement_timeout = '5s';                        -- SRS §12.8
ALTER ROLE svc_app SET idle_in_transaction_session_timeout = '10s';    -- SRS §12.8

-- 3. Conexión a la base ---------------------------------------------------------------
-- :"DBNAME" es la base a la que está conectado psql.
GRANT CONNECT ON DATABASE :"DBNAME" TO svc_migrator, svc_app;
-- La primera migración ejecuta `CREATE SCHEMA IF NOT EXISTS app`; PostgreSQL pide
-- CREATE sobre la base aunque el esquema ya exista. Solo el migrador lo recibe.
GRANT CREATE ON DATABASE :"DBNAME" TO svc_migrator;

-- 4. Esquemas -------------------------------------------------------------------------------
REVOKE ALL ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA IF NOT EXISTS app;
GRANT USAGE, CREATE ON SCHEMA app TO svc_migrator;   -- crea tablas, tipos e índices
GRANT USAGE          ON SCHEMA app TO svc_app;       -- solo usa lo que el migrador crea

-- 5. Privilegios por defecto de svc_app: SOLO SELECT, INSERT y UPDATE --------------------------
-- Valen para todo objeto que cree svc_migrator en `app`, hoy y en migraciones futuras.
-- No se concede DELETE, TRUNCATE, REFERENCES ni TRIGGER.
-- (ALTER DEFAULT PRIVILEGES FOR ROLE exige ser superusuario o miembro del rol.)
GRANT svc_migrator TO CURRENT_USER;

ALTER DEFAULT PRIVILEGES FOR ROLE svc_migrator IN SCHEMA app
    GRANT SELECT, INSERT, UPDATE ON TABLES TO svc_app;

-- INSERT en columnas autoincrementales (p. ej. audit_log.id) necesita USAGE en la
-- secuencia; es parte de poder insertar, no un privilegio adicional sobre los datos.
ALTER DEFAULT PRIVILEGES FOR ROLE svc_migrator IN SCHEMA app
    GRANT USAGE, SELECT ON SEQUENCES TO svc_app;

-- Idempotencia sobre objetos que ya existan (re-ejecución del script con tablas creadas)
GRANT SELECT, INSERT, UPDATE ON ALL TABLES    IN SCHEMA app TO svc_app;
GRANT USAGE, SELECT          ON ALL SEQUENCES IN SCHEMA app TO svc_app;
REVOKE DELETE, TRUNCATE, REFERENCES, TRIGGER ON ALL TABLES IN SCHEMA app FROM svc_app;

\echo 'bootstrap_roles.sql: roles svc_migrator y svc_app listos.'
