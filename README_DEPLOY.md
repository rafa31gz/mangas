# Despliegue en AWS EC2 con Docker Swarm

Esta guía describe cómo construir la imagen del bot, publicarla en Docker Hub y desplegarla en una instancia EC2 usando Docker Swarm. Incluye los comandos exactos para preparar el entorno local, inicializar el clúster y actualizar el servicio.

> **Nota:** Se añadió `version: "3.9"` a `docker-compose.yml` para que sea compatible con `docker stack deploy`. No requiere más cambios en la aplicación.

---

## 1. Prerrequisitos

- Docker 24+ (con soporte para Buildx) instalado en tu máquina local.
- Cuenta en [Docker Hub](https://hub.docker.com/) y sesión iniciada (`docker login`).
- Acceso SSH a una instancia EC2 con Docker instalado.
- Archivo `.env` con las variables sensibles necesarias para el bot.

Opcionalmente define algunas variables de entorno para reutilizarlas durante la sesión:

- **macOS / Linux (bash o zsh):**

  ```bash
  export DOCKERHUB_USER="tu_usuario"
  export IMAGE_NAME="mangas-bot"
  export IMAGE_TAG="$(date +%Y%m%d%H%M)"
  export IMAGE_URI="${DOCKERHUB_USER}/${IMAGE_NAME}:${IMAGE_TAG}"
  ```

- **Windows (PowerShell):**

  ```powershell
  $Env:DOCKERHUB_USER = "tu_usuario"
  $Env:IMAGE_NAME = "mangas-bot"
  $Env:IMAGE_TAG = (Get-Date -Format 'yyyyMMddHHmm')
  $Env:IMAGE_URI = "$Env:DOCKERHUB_USER/$Env:IMAGE_NAME:$Env:IMAGE_TAG"
  ```

---

## 2. Construir y publicar la imagen con Buildx

1. Asegúrate de tener un builder activo (solo la primera vez, comandos idénticos en macOS, Linux o Windows PowerShell):

   ```bash
   docker buildx create --name mangas-builder --use
   docker buildx inspect --bootstrap
   ```

2. Construye y publica la imagen multi-plataforma (ej. `linux/amd64`):

   - **macOS / Linux (bash o zsh):**

     ```bash
     docker buildx build \
       --platform linux/amd64 \
       --tag "${IMAGE_URI}" \
       --tag "${DOCKERHUB_USER}/${IMAGE_NAME}:latest" \
       --push \
       .
     ```

   - **Windows (PowerShell):**

     ```powershell
     docker buildx build `
       --platform linux/amd64 `
       --tag $Env:IMAGE_URI `
       --tag "$Env:DOCKERHUB_USER/$Env:IMAGE_NAME:latest" `
       --push `
       .
     ```

   - La primera etiqueta usa un tag inmutable (`$IMAGE_TAG`); la segunda actualiza `latest`.
   - Ajusta las plataformas según tus necesidades (p. ej. `linux/arm64` si tu EC2 es Graviton).

3. Verifica que la imagen esté en Docker Hub:

   - **macOS / Linux (bash o zsh):**

     ```bash
     docker manifest inspect "${IMAGE_URI}" | head
     ```

   - **Windows (PowerShell):**

     ```powershell
     docker manifest inspect $Env:IMAGE_URI | Select-Object -First 10
     ```

---

## 3. Preparar la instancia EC2

1. Conéctate por SSH (desde tu máquina local):

   - **macOS / Linux (bash o zsh):**

     ```bash
     ssh -i /ruta/a/tu.pem ubuntu@EC2_PUBLIC_IP
     ```

   - **Windows (PowerShell):**

     ```powershell
     ssh -i "C:\ruta\a\tu.pem" ubuntu@EC2_PUBLIC_IP
     ```

2. Instala Docker si aún no está disponible:

   - **Ubuntu / Debian:**

     ```bash
     curl -fsSL https://get.docker.com | sudo sh
     sudo usermod -aG docker "$USER"
     newgrp docker
     ```

   - **Red Hat Enterprise Linux 10 (usuario `ec2-user`):**

     ```bash
     sudo dnf -y install dnf-plugins-core
     sudo dnf config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo
     sudo dnf -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
     sudo systemctl enable --now docker
     sudo usermod -aG docker ec2-user
     exit
     ```

     > Vuelve a entrar por SSH después del `exit` para refrescar los grupos. Verifica que `ec2-user` esté en el grupo `docker` con `id ec2-user` o `groups`.

3. Inicia sesión en Docker Hub desde la instancia:

   ```bash
   docker login
   ```

4. Crea un directorio para el stack y valida permisos:

   ```bash
   sudo mkdir -p /opt/mangas
   sudo chown ec2-user:ec2-user /opt/mangas
   ls -ld /opt/mangas
   ```

5. Copia el `.env` y los archivos de despliegue (desde tu máquina local):

   - **macOS / Linux (bash o zsh):**

     ```bash
     scp -i /ruta/a/tu.pem .env ubuntu@EC2_PUBLIC_IP:/opt/mangas/.env
     scp -i /ruta/a/tu.pem stack.yml ubuntu@EC2_PUBLIC_IP:/opt/mangas/stack.yml
     ```

   - **Windows (PowerShell)** (ajusta la ruta del `.pem`):

     ```powershell
     scp -i "C:\ruta\a\tu.pem" .env ubuntu@EC2_PUBLIC_IP:/opt/mangas/.env
     scp -i "C:\ruta\a\tu.pem" stack.yml ubuntu@EC2_PUBLIC_IP:/opt/mangas/stack.yml
     ```

   - El archivo `stack.yml` incluido en este repositorio declara un volumen nombrado `mangas-data` (persistencia en Swarm) y usa la variable `DOCKER_IMAGE`. Antes de desplegar, define las variables necesarias en la instancia:

     ```bash
     export DOCKERHUB_USER="tu_usuario"
     export IMAGE_NAME="mangas-bot"
     export DOCKER_IMAGE="${DOCKERHUB_USER}/${IMAGE_NAME}:latest"
     echo "DOCKER_IMAGE=$DOCKER_IMAGE"
     ```

     > Asegúrate de anteponer `$` al consultar las variables (`echo $DOCKER_IMAGE`). Si prefieres evitar variables intermedias, puedes establecer el valor directamente: `export DOCKER_IMAGE="tu_usuario/mangas-bot:TAG"` (ej. `202411231200`).

---

## 5. Validar el stack en local antes de EC2

Aunque el despliegue final será en Swarm, conviene verificar que la imagen y el stack funcionan en tu máquina.

1. **(Opcional) Prueba rápida con Compose local**

   - Utiliza `docker-compose.yml` para levantar el servicio con tu `.env` local:

     ```bash
     docker compose up --build
     ```

   - Confirma que el bot inicia (revisa logs, endpoints, etc.). Detén el servicio con `CTRL+C` y limpia:

     ```bash
     docker compose down -v
     ```

2. **Prueba del stack con un Swarm local**

   - Inicializa Swarm en tu máquina (no afecta a EC2):

     ```bash
     docker swarm init
     ```

   - Desde la raíz del repositorio (donde está el `Dockerfile`), construye y etiqueta la imagen para usarla localmente **antes** de copiar nada a `/tmp`:

     ```bash
     docker build -t mangas-bot:local .
     ```

   - Crea un directorio temporal para aislar el stack y copia `stack.yml` y `.env`:

     ```bash
     mkdir -p /tmp/mangas-stack-test
     cp stack.yml .env /tmp/mangas-stack-test/
     cd /tmp/mangas-stack-test
     export DOCKER_IMAGE="mangas-bot:local"
     ```

     > Ya no es necesario volver a ejecutar `docker build` aquí; la imagen `mangas-bot:local` quedó almacenada en tu daemon. Si necesitas construir desde otro directorio, usa una ruta absoluta al Dockerfile, por ejemplo: `docker build -t mangas-bot:local -f /ruta/al/repo/Dockerfile /ruta/al/repo`.

   - Despliega el stack usando la imagen local que ya está en tu daemon:

     ```bash
     docker stack deploy -c stack.yml mangas-local
     docker stack services mangas-local
     docker service logs -f mangas-local_mangas-bot
     ```

   - Cuando termines, limpia:

     ```bash
     docker stack rm mangas-local
     docker swarm leave --force
     rm -rf /tmp/mangas-stack-test
     ```

3. Si las pruebas locales pasan, continúa con la sección 3 para preparar EC2.

---

## 4. Inicializar Docker Swarm y desplegar

1. En la instancia EC2, inicializa Swarm (si no existe):

   ```bash
   docker swarm init --advertise-addr "$(hostname -I | awk '{print $1}')"
   ```

   - Puedes operar con un único nodo **manager** sin workers: Swarm permitirá ejecutar los servicios en ese mismo nodo.
   - Si deseas añadir más nodos (workers o managers adicionales), guarda el token que muestra el comando.

2. (Opcional) Crea una red overlay específica:

   ```bash
   docker network create --driver overlay --attachable mangas-net
   ```

   Luego agrega `networks: [mangas-net]` al servicio en `stack.yml` si la usas.

3. Define la imagen a usar (si no lo hiciste antes):

   ```bash
   export DOCKERHUB_USER="${DOCKERHUB_USER:-tu_usuario}"
   export IMAGE_NAME="${IMAGE_NAME:-mangas-bot}"
   export DOCKER_IMAGE="${DOCKER_IMAGE:-${DOCKERHUB_USER}/${IMAGE_NAME}:latest}"
   echo "Usando imagen: $DOCKER_IMAGE"
   ```

   Sustituye `latest` por un tag específico si quieres un despliegue inmutable. También puedes asignar directamente `export DOCKER_IMAGE="tu_usuario/mangas-bot:TAG"`.

4. Despliega la pila:

   ```bash
   cd /opt/mangas
   docker stack deploy -c stack.yml mangas
   ```

5. Verifica el estado:

   ```bash
   docker stack services mangas
   docker service ps mangas_mangas-bot
   docker logs $(docker ps --filter name=mangas_mangas-bot --quiet) --tail 50
   ```

---

## 5. Actualizaciones y rollbacks

- Para desplegar una nueva versión:

  1. Repite el build/push con un nuevo tag.
  2. Actualiza `stack.yml` con la nueva referencia (`image: usuario/mangas-bot:nuevo-tag`).
  3. Ejecuta de nuevo `docker stack deploy -c stack.yml mangas`.

- Si algo sale mal, vuelve a la versión anterior editando el `stack.yml` y redeployando.

- Para un rollback rápido sin editar el archivo:

  ```bash
  docker service update --image usuario/mangas-bot:tag_anterior mangas_mangas-bot
  ```

---

## 6. Limpieza opcional

- Elimina servicios y stacks:

  ```bash
  docker stack rm mangas
  ```

- Sal de Swarm (solo si no lo necesitas):

  ```bash
  docker swarm leave --force
  ```

- Borra imágenes antiguas:

  ```bash
  docker image prune
  ```

---

### Resumen de cambios aplicados

- Se añadió `version: "3.9"` a `docker-compose.yml` para compatibilidad con `docker stack deploy`.
- El resto del despliegue se basa en los archivos ya existentes (`Dockerfile`, `docker-compose.yml`).

Con esto deberías poder construir, publicar y desplegar el bot en tu infraestructura de AWS EC2 sin pasos adicionales. ¡Buen despliegue!
