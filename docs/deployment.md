# 🚀 Despliegue — Cold Start a Producción

## Requisitos

- VM Debian 12/13 con acceso SSH
- Puerto 80/443 abiertos en firewall (NSG en Azure)
- Dominio apuntando a la IP (ej: `ecae.me`)

## Cold Start (VM desde cero)

```bash
git clone https://github.com/EliKat2005/OptiBus-PWA.git
cd OptiBus-PWA
./scripts/setup_host.sh
# ⚠️ Cerrar y reabrir sesión SSH
./scripts/generate_env.sh
nano .env  # Configurar OPTIBUS_API_KEY y DOMAIN
./deploy.sh
./scripts/seed_db.sh  # Opcional: ingerir datos pre-grabados
```

## Actualizar VM existente

```bash
cd ~/OptiBus-PWA
git pull origin main
./deploy.sh
```

## Opciones de deploy.sh

| Comando | Descripción |
|---------|-------------|
| `./deploy.sh` | Build completo + pull + up |
| `./deploy.sh --quick` | Restart sin rebuild |
| `./deploy.sh --rollback` | Revertir al backup pre-deploy |
| `./deploy.sh --status` | Ver estado de servicios |

## Scripts de soporte

| Script | Función |
|--------|---------|
| `scripts/setup_host.sh` | Instalar podman, linger, puertos 80/443 |
| `scripts/generate_env.sh` | Generar .env con contraseñas aleatorias |
| `scripts/seed_db.sh` | Ingerir GPX/JSON desde `backend/seed_data/` |
| `scripts/backup-db.sh` | Backup comprimido de PostgreSQL |
| `scripts/restore-db.sh` | Restaurar backup |

## Acceso a servicios internos

```bash
# SSH tunnel para acceder desde PC local
ssh -L 8000:localhost:8000 -L 3000:localhost:3000 azureuser@<ip>
# Admin Dashboard: http://localhost:8000/admin?api_key=<key>
# Grafana: http://localhost:3000 (admin / contraseña en .env)
```

## Backup automático (crontab)

```bash
crontab -e
# Backup diario a las 2:00 AM:
0 2 * * * /home/azureuser/OptiBus-PWA/scripts/backup-db.sh /home/azureuser/backups