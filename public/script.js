document.addEventListener('DOMContentLoaded', async function () {
  mostrarLoader();
  await cargarMangas();
  ocultarLoader();
});

// 🟢 Cargar lista de mangas y progreso
async function cargarMangas() {
  const response = await fetch('/mangas');
  const mangas = await response.json();
  const tbody = document.getElementById('manga-table');
  tbody.innerHTML = '';

  for (const manga of mangas) {
    await agregarFilaManga(manga);
  }
}

async function agregarFilaManga(manga) {
  const tbody = document.getElementById('manga-table');

  // Obtener progreso de lectura
  const capProgreso = parseFloat(manga.capitulo_actual) || 0; // Asegurarse de que sea un número decimal
  const ultimoCap = parseFloat(manga.ultimo_capitulo) || 1; // Asegurar que sea un número decimal
  const progreso = Math.min((capProgreso / ultimoCap) * 100, 100); // Calcular el progreso como porcentaje

  // Color del progreso
  let colorClase = 'bg-danger';
  if (capProgreso === ultimoCap) colorClase = 'bg-success';
  else if (capProgreso >= ultimoCap * 0.8) colorClase = 'bg-warning';

  // Crear fila
  const fila = document.createElement('tr');
  fila.setAttribute('id', `fila_${manga.id}`);
  fila.innerHTML = `
        <td>${manga.id}</td>
        <td>${manga.nombre}</td>
        <td><a href="${
          manga.url
        }" target="_blank" class="btn btn-sm btn-primary">🔗 Ver</a></td>
        <td id="cap_${manga.id}">${manga.ultimo_capitulo || '-'}</td>
        <td id="fecha_${manga.id}">${manga.fecha_consulta || '-'}</td>
        <td id="progreso_${manga.id}">
            ${capProgreso.toFixed(1)} / ${ultimoCap.toFixed(1) || '?'}
            <div class="progress" style="height: 20px; margin-top: 5px;">
                <div id="barra_${
                  manga.id
                }" class="progress-bar ${colorClase}" role="progressbar" 
                    style="width: ${progreso}%" aria-valuenow="${progreso}" 
                    aria-valuemin="0" aria-valuemax="100">${progreso.toFixed(
                      2
                    )}%</div> <!-- Mostrar el progreso con 2 decimales -->
            </div>
        </td>
        <td>
            <button class="btn btn-sm btn-info" onclick="consultarManga(${
              manga.id
            })">🔄 Actualizar</button>
            <button class="btn btn-sm btn-danger" onclick="eliminarManga(${
              manga.id
            })">❌ Eliminar</button>
            <button class="btn btn-sm btn-secondary" onclick="abrirModalProgreso(${
              manga.id
            }, ${capProgreso}, ${ultimoCap})">📖 Progreso</button>
        </td>
    `;
  tbody.appendChild(fila);
}



// 🟢 Consultar manga y actualizar sin recargar
async function consultarManga(id) {
  mostrarLoader();
  try {
    const response = await fetch(`/manga/${id}`);
    const data = await response.json();

    // Actualizar el número del último capítulo y la fecha
    document.getElementById(`cap_${id}`).innerHTML =
      data.ultimo_capitulo +
      (data.nuevo ? ' <span class="badge bg-danger">NEW!</span>' : '');
    document.getElementById(`fecha_${id}`).innerText = data.fecha;

    // Obtener el progreso y el último capítulo (permitiendo decimales)
    const capituloActual = parseFloat(data.capitulo_actual) || 0; // Progreso del capítulo
    const ultimoCapitulo = parseFloat(data.ultimo_capitulo) || 1; // Último capítulo

    // Evitar divisiones por 0
    const progreso =
      ultimoCapitulo > 0
        ? Math.min((capituloActual / ultimoCapitulo) * 100, 100)
        : 0;

    // Actualizar el texto de progreso con decimales
    const progresoText = `${capituloActual} / ${ultimoCapitulo}`;
    const progresoElement = document.getElementById(`progreso_${id}`);

    if (progresoElement) {
      // Actualizar el texto de la barra de progreso
      progresoElement.querySelector(
        '.progress-bar'
      ).innerText = `${progreso.toFixed(1)}%`;
      progresoElement.querySelector(
        '.progress-bar'
      ).style.width = `${progreso}%`;

      // Cambiar el color de la barra de progreso según el avance
      let colorClase =
        progreso === 100
          ? 'bg-success'
          : progreso >= 80
          ? 'bg-warning'
          : 'bg-danger';
      progresoElement.querySelector(
        '.progress-bar'
      ).className = `progress-bar ${colorClase}`;
    }
  } catch (error) {
    console.error('Error al consultar manga:', error);
  } finally {
    ocultarLoader();
  }
}

// 🟢 Eliminar manga sin recargar la página
async function eliminarManga(id) {
  if (!confirm('¿Seguro que quieres eliminar este manga?')) return;

  mostrarLoader();
  try {
    const response = await fetch(`/mangas/${id}`, { method: 'DELETE' });
    if (!response.ok) throw new Error('Error al eliminar el manga.');

    document.getElementById(`fila_${id}`).remove();
  } catch (error) {
    console.error('Error al eliminar manga:', error);
  } finally {
    ocultarLoader();
  }
}

// 🟢 Agregar manga sin recargar
async function agregarManga() {
  const nombre = document.getElementById('nombreManga').value.trim();
  const url = document.getElementById('urlManga').value.trim();

  if (!nombre || !url) return;

  mostrarLoader();
  try {
    const response = await fetch('/mangas', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nombre, url }),
    });

    if (!response.ok) throw new Error('Error al agregar el manga.');

    const nuevoManga = await response.json();
    await agregarFilaManga(nuevoManga); // Agregar fila sin recargar
  } catch (error) {
    console.error('Error al agregar manga:', error);
  } finally {
    ocultarLoader();
  }
}

// 🟢 Abrir modal para actualizar progreso
function abrirModalProgreso(id, capActual, ultimoCapitulo) {
  document.getElementById('mangaId').value = id;
  document.getElementById('capituloActual').value = parseFloat(capActual) || 0;
  document.getElementById('ultimoCapitulo').value =
    parseFloat(ultimoCapitulo) || 0;
  
  let modal = new bootstrap.Modal(document.getElementById('modalProgreso'));
  modal.show();
}

// 🟢 Guardar progreso sin recargar
async function actualizarProgreso() {
  const id = document.getElementById('mangaId').value;
  const capitulo = document.getElementById('capituloActual').value.trim();
  const ultimo_capitulo = document
    .getElementById('ultimoCapitulo')
    .value.trim();

  if (!capitulo) return;

  mostrarLoader();
  try {
    const response = await fetch(`/progreso/${id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ capitulo_actual: capitulo }),
    });

    if (!response.ok) throw new Error('Error al actualizar el progreso.');

    actualizarProgresoUI(id, capitulo, ultimo_capitulo);
  } catch (error) {
    console.error('Error al actualizar el progreso:', error);
  } finally {
    ocultarLoader();
    let modal = bootstrap.Modal.getInstance(
      document.getElementById('modalProgreso')
    );
    modal.hide();
  }
}
// 🟢 Actualizar la UI del progreso sin recargar
async function actualizarProgresoUI(id, capitulo_actual, ultimo_capitulo) {
  const capProgreso = parseFloat(capitulo_actual) || 0; // Asegurar que sea número válido con decimales
  const ultimoCapitulo = parseFloat(ultimo_capitulo) || 1; // Si no es válido, por defecto 1 (evita división por 0)

  // Obtener los elementos de la UI
  const progresoElement = document.getElementById(`progreso_${id}`);
  const barraProgreso = document.getElementById(`barra_${id}`);

  if (progresoElement && barraProgreso) {
    // Calcular el progreso
    const progreso =
      ultimoCapitulo > 0
        ? Math.min((capProgreso / ultimoCapitulo) * 100, 100)
        : 0;

    // Determinar color según el progreso
    const barraColor =
      progreso === 100
        ? 'bg-success'
        : progreso >= 80
        ? 'bg-warning'
        : 'bg-danger';

    // Actualizar la barra de progreso
    barraProgreso.style.width = `${progreso}%`;
    barraProgreso.innerText = `${progreso.toFixed(1)}%`; // Mostrar porcentaje con 1 decimal
    barraProgreso.className = `progress-bar ${barraColor}`;

    // Reemplazar el contenido del elemento de progreso
    progresoElement.innerHTML = `
            ${capProgreso} / ${ultimoCapitulo}
            <div class="progress" style="height: 20px; margin-top: 5px;">
                ${barraProgreso.outerHTML}
            </div>
        `;
  } else {
    console.error(
      `Elemento con id "progreso_${id}" o "barra_${id}" no encontrado.`
    );
  }
}

// 🟢 Loader de carga
function mostrarLoader() {
  document.getElementById('loader').style.display = 'flex';
}
function ocultarLoader() {
  document.getElementById('loader').style.display = 'none';
}

// 🟢 Registrar Service Worker para PWA
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js');
}

// 🟢 Solicitar permisos de notificación
if (Notification.permission === 'default') {
  Notification.requestPermission();
}

// 🟢 Función para actualizar todos los mangas y buscar nuevos capítulos
async function actualizarTodosLosMangas() {
  mostrarLoader(); // Mostrar el loader mientras se actualizan los mangas

  try {
    // Realizar la solicitud para actualizar todos los mangas
    const response = await fetch('/mangas/actualizar-todos', {
      method: 'POST',
    });

    // Verificar si la respuesta fue exitosa
    if (!response.ok) {
      throw new Error('No se pudo actualizar los mangas');
    }

    // Obtener la respuesta con los mangas actualizados
    const result = await response.json();

    // Notificar al usuario que la actualización fue exitosa
    alert(`¡Todos los mangas han sido actualizados! ${result.mensaje}`);

    // Actualizar la tabla con los nuevos datos
    await cargarMangas();
  } catch (error) {
    alert('Hubo un error al actualizar los mangas: ' + error.message);
  } finally {
    ocultarLoader(); // Ocultar el loader una vez terminada la actualización
  }
}

// Filtrar la tabla de mangas
function filtrarTabla() {
  const searchInput = document
    .getElementById('searchInput')
    .value.toLowerCase();
  const filterSelect = document.getElementById('filterSelect').value;

  const filas = document.querySelectorAll('#manga-table tr');

  filas.forEach((fila) => {
    const nombre = fila
      .querySelector('td:nth-child(2)')
      .textContent.toLowerCase();
    const ultimoCapitulo =
      parseInt(fila.querySelector('td:nth-child(4)').textContent) || 0;
    const progreso =
      parseFloat(
        fila.querySelector('.progress-bar').getAttribute('aria-valuenow')
      ) || 0;
    const esNuevo = fila.querySelector('.badge') !== null;

    let mostrar = true;

    // Filtro de búsqueda por nombre
    if (nombre.indexOf(searchInput) === -1) {
      mostrar = false;
    }

    // Filtro por estado (Nuevos, Completados, No Completados)
    if (filterSelect === 'nuevos' && !esNuevo) {
      mostrar = false;
    } else if (filterSelect === 'completados' && progreso !== 100) {
      mostrar = false;
    } else if (filterSelect === 'noCompletados' && progreso === 100) {
      mostrar = false;
    }

    fila.style.display = mostrar ? '' : 'none';
  });
}

// Ordenar por progreso
function ordenarTabla() {
  const filas = Array.from(document.querySelectorAll('#manga-table tr'));
  filas.sort((a, b) => {
    const progresoA =
      parseFloat(
        a.querySelector('.progress-bar').getAttribute('aria-valuenow')
      ) || 0;
    const progresoB =
      parseFloat(
        b.querySelector('.progress-bar').getAttribute('aria-valuenow')
      ) || 0;
    return progresoB - progresoA; // Ordenar de mayor a menor progreso
  });
  filas.forEach((fila) =>
    document.getElementById('manga-table').appendChild(fila)
  );
}
