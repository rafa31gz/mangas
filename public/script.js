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
  if (!mangas.length) {
    prepararEncabezadoFlotante();
  }
  actualizarVisibilidadEncabezadoFlotante();
}

async function agregarFilaManga(manga) {
  const tbody = document.getElementById('manga-table');

  // Obtener progreso de lectura
  const capProgresoNumero = parseFloat(manga.capitulo_actual);
  const capProgreso = Number.isFinite(capProgresoNumero)
    ? capProgresoNumero
    : 0; // Asegurarse de que sea un número decimal
  const ultimoCapNumero = parseFloat(manga.ultimo_capitulo);
  const ultimoCapReferencia =
    Number.isFinite(ultimoCapNumero) && ultimoCapNumero > 0
      ? ultimoCapNumero
      : capProgreso > 0
      ? capProgreso
      : 1; // Evita división por cero y usa progreso como respaldo
  const progreso =
    ultimoCapReferencia > 0
      ? Math.min((capProgreso / ultimoCapReferencia) * 100, 100)
      : 0; // Calcular el progreso como porcentaje
  const progresoTexto = Number.isInteger(capProgreso)
    ? capProgreso
    : capProgreso.toFixed(1);
  const ultimoTexto =
    Number.isFinite(ultimoCapNumero) && ultimoCapNumero > 0
      ? Number.isInteger(ultimoCapNumero)
        ? ultimoCapNumero
        : ultimoCapNumero.toFixed(1)
      : '?';
  const ultimoCapituloTexto =
    manga.ultimo_capitulo !== undefined &&
    manga.ultimo_capitulo !== null &&
    String(manga.ultimo_capitulo).trim() !== ''
      ? manga.ultimo_capitulo
      : '-';
  const badgeNuevo = manga.nuevo
    ? ' <span class="badge bg-danger">NEW!</span>'
    : '';
  const ultimoCapParaModal = Number.isFinite(ultimoCapNumero)
    ? ultimoCapNumero
    : ultimoCapReferencia;

  // Color del progreso
  let colorClase = 'bg-danger';
  if (ultimoCapReferencia > 0 && capProgreso >= ultimoCapReferencia) {
    colorClase = 'bg-success';
  } else if (capProgreso >= ultimoCapReferencia * 0.8) {
    colorClase = 'bg-warning';
  }

  // Crear fila
  let fila = document.getElementById(`fila_${manga.id}`);
  const filaExistente = Boolean(fila);
  if (!fila) {
    fila = document.createElement('tr');
    fila.setAttribute('id', `fila_${manga.id}`);
  }
  fila.innerHTML = `
        <td data-label="Nombre">${manga.nombre}</td>
        <td data-label="Ver"><a href="${
          manga.url
        }" target="_blank" class="btn btn-sm btn-primary">🔗 Ver</a></td>
        <td data-label="Último Capítulo" id="cap_${manga.id}">${ultimoCapituloTexto}${badgeNuevo}</td>
        <td data-label="Última Consulta" id="fecha_${manga.id}">${
          manga.fecha_consulta || '-'
        }</td>
        <td data-label="Progreso" id="progreso_${manga.id}">
            <span id="progreso_text_${manga.id}">${progresoTexto} / ${ultimoTexto}</span>
            <div class="progress" style="height: 20px; margin-top: 5px;">
                <div id="barra_${
                  manga.id
                }" class="progress-bar ${colorClase}" role="progressbar" 
                    style="width: ${progreso}%" aria-valuenow="${progreso.toFixed(2)}" 
                    aria-valuemin="0" aria-valuemax="100">${progreso.toFixed(
                      2
                    )}%</div> <!-- Mostrar el progreso con 2 decimales -->
            </div>
        </td>
        <td data-label="Acciones" class="acciones-cell">
            <div class="d-none d-md-flex gap-1 flex-wrap action-buttons-desktop">
                <button class="btn btn-sm btn-info" data-accion="actualizar" onclick="consultarManga(${
                  manga.id
                })">🔄 Actualizar</button>
                <button class="btn btn-sm btn-danger" data-accion="eliminar" onclick="eliminarManga(${
                  manga.id
                })">❌ Eliminar</button>
                <button class="btn btn-sm btn-secondary" data-accion="progreso" onclick="abrirModalProgreso(${
                  manga.id
                }, ${capProgreso}, ${ultimoCapParaModal})">📖 Progreso</button>
            </div>
            <div class="dropdown d-md-none action-buttons-mobile">
                <button class="btn btn-sm btn-outline-secondary dropdown-toggle icon-ellipsis" type="button" data-bs-toggle="dropdown" aria-expanded="false" aria-label="Más acciones">
                    &#8942;
                </button>
                <ul class="dropdown-menu dropdown-menu-end">
                    <li><button class="dropdown-item" data-accion="actualizar" onclick="consultarManga(${manga.id})">Actualizar</button></li>
                    <li><button class="dropdown-item text-danger" data-accion="eliminar" onclick="eliminarManga(${manga.id})">Eliminar</button></li>
                    <li><button class="dropdown-item" data-accion="progreso" onclick="abrirModalProgreso(${manga.id}, ${capProgreso}, ${ultimoCapParaModal})">Progreso</button></li>
                </ul>
            </div>
        </td>
    `;
  if (!filaExistente) {
    tbody.appendChild(fila);
  }
  prepararEncabezadoFlotante();
}

function obtenerTablaMangas() {
  return document.querySelector('.responsive-table');
}

function prepararEncabezadoFlotante() {
  const tabla = obtenerTablaMangas();
  const contenedorFlotante = document.getElementById(
    'tablaMangasFloatingHeader'
  );

  if (!tabla || !contenedorFlotante) return;

  const thead = tabla.querySelector('thead');
  if (!thead) return;

  let tablaClon = contenedorFlotante.querySelector('table');
  if (!tablaClon) {
    tablaClon = document.createElement('table');
    tablaClon.className = 'table table-striped mb-0';
    contenedorFlotante.appendChild(tablaClon);
  }

  const nuevoThead = thead.cloneNode(true);
  tablaClon.innerHTML = '';
  tablaClon.appendChild(nuevoThead);
  actualizarVisibilidadEncabezadoFlotante();
}

function actualizarVisibilidadEncabezadoFlotante() {
  const tabla = obtenerTablaMangas();
  const contenedorFlotante = document.getElementById(
    'tablaMangasFloatingHeader'
  );

  if (!tabla || !contenedorFlotante) return;

  if (window.innerWidth > 768) {
    contenedorFlotante.classList.remove('visible');
    return;
  }

  const tablaRect = tabla.getBoundingClientRect();
  const scrollTop =
    window.scrollY ||
    document.documentElement.scrollTop ||
    document.body.scrollTop ||
    0;
  const tablaOffsetTop = tablaRect.top + scrollTop;
  const triggerPoint =
    tablaOffsetTop + Math.max(tabla.offsetHeight * 0.5, 100);

  if (scrollTop >= triggerPoint) {
    contenedorFlotante.classList.add('visible');
  } else {
    contenedorFlotante.classList.remove('visible');
  }
}

window.addEventListener(
  'scroll',
  () => {
    actualizarVisibilidadEncabezadoFlotante();
  },
  { passive: true }
);

window.addEventListener('resize', () => {
  prepararEncabezadoFlotante();
  actualizarVisibilidadEncabezadoFlotante();
});



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

    actualizarProgresoUI(id, capituloActual, ultimoCapitulo);
  } catch (error) {
    console.error('Error al consultar manga:', error);
  } finally {
    ocultarLoader();
    actualizarVisibilidadEncabezadoFlotante();
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
    actualizarVisibilidadEncabezadoFlotante();
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

    let payload = null;
    try {
      payload = await response.json();
    } catch (parseError) {
      payload = null;
    }

    if (!response.ok) {
      const mensajeError =
        (payload && payload.error) ||
        'No se pudo agregar el manga. Verifica la información.';
      alert(mensajeError);
      if (payload && payload.manga) {
        await agregarFilaManga({ ...payload.manga, nuevo: false });
      }
      return;
    }

    if (payload) {
      await agregarFilaManga(payload); // Agregar o actualizar fila sin recargar
      alert(payload.mensaje || 'Manga agregado correctamente');
    }

    document.getElementById('nombreManga').value = '';
    document.getElementById('urlManga').value = '';
  } catch (error) {
    console.error('Error al agregar manga:', error);
    alert('Ocurrió un error al agregar el manga. Intenta nuevamente.');
  } finally {
    ocultarLoader();
    actualizarVisibilidadEncabezadoFlotante();
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
    const modalElemento = document.getElementById('modalProgreso');
    const modal = modalElemento
      ? bootstrap.Modal.getInstance(modalElemento)
      : null;
    if (modal) modal.hide();
    actualizarVisibilidadEncabezadoFlotante();
  }
}
// 🟢 Actualizar la UI del progreso sin recargar
async function actualizarProgresoUI(id, capitulo_actual, ultimo_capitulo) {
  const progresoElement = document.getElementById(`progreso_${id}`);
  if (!progresoElement) {
    console.error(`Elemento con id "progreso_${id}" no encontrado.`);
    return;
  }

  const capProgreso = parseFloat(capitulo_actual) || 0; // Asegurar que sea número válido con decimales
  const ultimoCapitulo = parseFloat(ultimo_capitulo) || 1; // Si no es válido, por defecto 1 (evita división por 0)

  const progreso =
    ultimoCapitulo > 0
      ? Math.min((capProgreso / ultimoCapitulo) * 100, 100)
      : 0;

  const barraColor =
    progreso === 100
      ? 'bg-success'
      : progreso >= 80
      ? 'bg-warning'
      : 'bg-danger';

  const formatearNumero = (valor) =>
    Number.isInteger(valor) ? valor : valor.toFixed(1);

  progresoElement.innerHTML = `
        <span id="progreso_text_${id}">${formatearNumero(
    capProgreso
  )} / ${formatearNumero(ultimoCapitulo)}</span>
        <div class="progress" style="height: 20px; margin-top: 5px;">
            <div id="barra_${id}" class="progress-bar ${barraColor}" role="progressbar"
                style="width: ${progreso}%"
                aria-valuenow="${progreso.toFixed(1)}" aria-valuemin="0" aria-valuemax="100">
                ${progreso.toFixed(1)}%
            </div>
        </div>
    `;

  const botonesProgreso = document.querySelectorAll(
    `#fila_${id} [data-accion="progreso"]`
  );
  botonesProgreso.forEach((boton) => {
    boton.setAttribute(
      'onclick',
      `abrirModalProgreso(${id}, ${capProgreso}, ${ultimoCapitulo})`
    );
  });
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

    if (Array.isArray(result.resultados)) {
      result.resultados.forEach((manga) => {
        const { id, ultimo_capitulo, capitulo_actual, fecha, nuevo } = manga;

        const capituloElemento = document.getElementById(`cap_${id}`);
        if (capituloElemento) {
          capituloElemento.innerHTML =
            `${ultimo_capitulo}` +
            (nuevo ? ' <span class="badge bg-danger">NEW!</span>' : '');
        }

        const fechaElemento = document.getElementById(`fecha_${id}`);
        if (fechaElemento && fecha) {
          fechaElemento.textContent = fecha;
        }

        actualizarProgresoUI(id, capitulo_actual, ultimo_capitulo);
      });
    } else {
      await cargarMangas();
    }

    if (result.mensaje) {
      alert(`¡Actualización completada! ${result.mensaje}`);
    }
  } catch (error) {
    alert('Hubo un error al actualizar los mangas: ' + error.message);
  } finally {
    ocultarLoader(); // Ocultar el loader una vez terminada la actualización
    actualizarVisibilidadEncabezadoFlotante();
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
    const nombreCelda = fila.querySelector('td[data-label="Nombre"]');
    const nombre = nombreCelda
      ? nombreCelda.textContent.toLowerCase()
      : '';
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
