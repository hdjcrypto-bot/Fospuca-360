import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, date, time
import io
import textwrap
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

# --- CONFIGURACIÓN DE BASE DE DATOS ---
Base = declarative_base()

class UsuarioSistema(Base):
    __tablename__ = 'usuarios_sistema'
    id = Column(Integer, primary_key=True)
    nombre = Column(String(100))
    telefono = Column(String(20))
    usuario = Column(String(50), unique=True)
    password = Column(String(50))
    sede_origen = Column(String(50))

class Sede(Base):
    __tablename__ = 'sedes'
    id = Column(Integer, primary_key=True)
    nombre = Column(String(50), unique=True)

class Personal(Base):
    __tablename__ = 'personal'
    id = Column(Integer, primary_key=True)
    nombre = Column(String(100))
    cedula = Column(String(20))
    telefono = Column(String(20))
    cargo = Column(String(50))
    sede_id = Column(Integer, ForeignKey('sedes.id'))
    en_guardia = Column(Boolean, default=False) 
    en_guardia_taller = Column(Boolean, default=False)

class Unidad(Base):
    __tablename__ = 'unidades'
    id = Column(Integer, primary_key=True)
    numero = Column(String(10), unique=True)
    sede_id = Column(Integer, ForeignKey('sedes.id'))
    estatus_fijo = Column(String(20), default="OPERATIVA") 

class TurnoSede(Base):
    __tablename__ = 'turnos_sede'
    id = Column(Integer, primary_key=True)
    sede_id = Column(Integer, ForeignKey('sedes.id'))
    operador = Column(String(50))
    hora_inicio = Column(DateTime, default=datetime.now)
    hora_fin = Column(DateTime, nullable=True)
    activo = Column(Boolean, default=True)

class ControlDiario(Base):
    __tablename__ = 'control_diario'
    id = Column(Integer, primary_key=True)
    unidad_id = Column(Integer, ForeignKey('unidades.id'))
    conductor_id = Column(Integer, ForeignKey('personal.id'))
    hora_salida = Column(DateTime, nullable=True)
    hora_entrada = Column(DateTime, nullable=True)
    es_externo = Column(Boolean, default=False)
    fecha = Column(DateTime, default=datetime.now)

class Novedad(Base):
    __tablename__ = 'novedades'
    id = Column(Integer, primary_key=True)
    unidad_id = Column(Integer, ForeignKey('unidades.id'), nullable=True) 
    turno_id = Column(Integer, ForeignKey('turnos_sede.id'))
    hora = Column(DateTime, default=datetime.now)
    tipo = Column(String(50))
    detalle = Column(Text)
    operador = Column(String(50))

# Conexión persistente
engine = create_engine('sqlite:///fospuca_control.db')
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
db = Session()

# Inicialización de Sedes
sedes_nombres = ["MANEIRO", "SAN DIEGO", "IRIBARREN", "GIRARDOT", "MARACAIBO", "BARUTA", "CHACAO", "HATILLO"]
for s in sedes_nombres:
    if not db.query(Sede).filter_by(nombre=s).first():
        db.add(Sede(nombre=s))
db.commit()

# --- ESTILOS CSS ---
st.set_page_config(layout="wide", page_title="Fospuca Control 360")
st.markdown("""
    <style>
    .status-card { padding: 6px; border-radius: 8px; color: white; text-align: center; font-weight: bold; font-size: 14px; box-shadow: 2px 2px 5px rgba(0,0,0,0.2);}
    .en-ruta { background-color: #28a745; }
    .en-resguardo { background-color: #007bff; }
    .en-externo { background-color: #17a2b8; }
    .en-sede { background-color: #6c757d; }
    .en-taller { background-color: #dc3545; }
    
    .kpi-card { background-color: #212529; color: white; border-left: 6px solid; padding: 20px; border-radius: 8px; box-shadow: 3px 3px 10px rgba(0,0,0,0.3);}
    .kpi-num { font-size: 28px; font-weight: bold; margin:0;}
    
    .directorio-box { background-color: #b7edc0; color: #212529; padding: 6px; border-radius: 6px; margin-bottom: 8px; border-left: 4px solid #6c757d; font-size: 16px;}
    .directorio-box-active { background-color: #d4edda; color: #155724; padding: 6px; border-radius: 6px; margin-bottom: 8px; border-left: 4px solid #28a745; font-size: 14px; font-weight: bold;}
    
    .sede-activa-card { background-color: #212529; color: white; padding: 10px; border-radius: 8px; margin-bottom: 10px; border-left: 6px solid #28a745; box-shadow: 2px 2px 5px rgba(0,0,0,0.3);}
    .sede-pausa-card { background-color: #212529; color: white; padding: 10px; border-radius: 8px; margin-bottom: 10px; border-left: 6px solid #ffc107; box-shadow: 2px 2px 5px rgba(0,0,0,0.3);}
    .sede-inactiva-card { background-color: #212529; color: #6c757d; padding: 10px; border-radius: 8px; margin-bottom: 10px; border-left: 6px solid #6c757d; box-shadow: 2px 2px 5px rgba(0,0,0,0.3);}
    </style>
    
""", unsafe_allow_html=True)

# Lógica de Sesión Multisede
if 'vista_actual' not in st.session_state: st.session_state.vista_actual = "DASHBOARD"
if 'auth_sedes' not in st.session_state: st.session_state.auth_sedes = {} 
if 'is_admin' not in st.session_state: st.session_state.is_admin = False

# --- FUNCIONES AUXILIARES ---
def generar_pdf_turno(turno, sede_nombre):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    
    # 1. LOGO FOSPUCA SUPERIOR IZQUIERDA
    try:
        logo_url = "https://fospuca.com/wp-content/uploads/2018/08/fospuca-logo.png"
        logo = ImageReader(logo_url)
        c.drawImage(logo, 50, 715, width=120, height=50, preserveAspectRatio=True, mask='auto')
    except Exception:
        pass # Si no hay internet para el logo, no detiene la creación del PDF
    
    # 2. CALCULO DIURNO/NOCTURNO PARA TÍTULO
    hora_cierre = turno.hora_fin if turno.hora_fin else datetime.now()
    h = hora_cierre.hour
    if 6 <= h < 19:
        tipo_guardia = "Diurna"
    else:
        tipo_guardia = "Nocturna"
        
    titulo = f"Entrega de Guardia {tipo_guardia} {sede_nombre}"
    
    # TITULO CENTRADO
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(306, 735, titulo) # 306 es el centro horizontal exacto
    
    # Línea separadora
    c.setLineWidth(1)
    c.line(50, 705, 560, 705)
    
    c.setFont("Helvetica", 10)


    # EXTRAER NOMBRE REAL DEL TITULAR
    if turno.operador.startswith("PAUSA:"):
        nombre_titular = turno.operador.split(":")[1]
    elif turno.operador.startswith("RELEVO:"):
        nombre_titular = turno.operador.split(":")[2]
    else:
        nombre_titular = turno.operador
        
    c.setFont("Helvetica", 10)
    
    sup_guardia = db.query(Personal).filter_by(
        sede_id=turno.sede_id, 
        cargo="Supervisor de Guardia", 
        en_guardia=True
    ).first()
    nombre_sup = sup_guardia.nombre if sup_guardia else "No asignado"

    c.drawString(50, 690, f"Analista: {nombre_titular}")
    c.drawString(50, 675, f"Inicio: {turno.hora_inicio.strftime('%H:%M  %Y-%m-%d')}")
    c.drawString(50, 660, f"Fin: {hora_cierre.strftime('%H:%M  %Y-%m-%d')}")
    c.drawString(50, 645, f"Sup. Oper. Guardia: {nombre_sup}")

    c.setLineWidth(1)
    c.line(50, 635, 560, 635)

    
    y = 620
    
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "1. UNIDADES QUE SALIERON A RUTA:")
    y -= 20


    c.setFont("Helvetica", 10)
    salidas_turno = db.query(ControlDiario).join(Unidad).filter(
        Unidad.sede_id == turno.sede_id, 
        ControlDiario.hora_salida >= turno.hora_inicio,
        ControlDiario.hora_salida <= hora_cierre
    ).order_by(ControlDiario.hora_salida).all()
    
    if not salidas_turno:
        c.drawString(50, y, "No se registró salida durante este turno.")
        y -= 15
    else:
        unidades_mostradas = set()
        for ctrl in salidas_turno:
            if ctrl.unidad_id in unidades_mostradas:
                continue
            unidades_mostradas.add(ctrl.unidad_id) 
            u = db.query(Unidad).filter_by(id=ctrl.unidad_id).first()
            p = db.query(Personal).filter_by(id=ctrl.conductor_id).first()
            c.drawString(50, y, f"- Unidad {u.numero} | Cond: {p.nombre}")
            y -= 15
            if y < 150: c.showPage(); y = 750

    y -= 10

    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "2. UNIDADES QUE QUEDAN EN RUTA:")
    y -= 20
    c.setFont("Helvetica", 10)
    
    en_ruta_actual = []
    unidades_sede = db.query(Unidad).filter_by(sede_id=turno.sede_id).all()
    for u in unidades_sede:
        ctrl = db.query(ControlDiario).filter_by(unidad_id=u.id).order_by(ControlDiario.id.desc()).first()
        if ctrl and ctrl.hora_salida and not ctrl.hora_entrada:
            en_ruta_actual.append(u.numero)
            
    if not en_ruta_actual:
        c.drawString(50, y, "Todas las unidades se encuentran en Sede o Resguardo.")
        y -= 15
    else:
        c.drawString(50, y, f"Unidades Fuera de Sede: {', '.join(en_ruta_actual)}")
        y -= 15

    y -= 10
    if y < 250: # Aumentamos el margen para que las áreas de sede quepan
        c.showPage()
        y = 750

    # --- SECCIÓN 3: NOVEDADES DE UNIDADES ---
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "3. NOVEDADES DE UNIDADES OPERATIVAS:")
    y -= 20
    c.setFont("Helvetica", 10)
    
    # Filtramos novedades que tengan unidad_id (las de los camiones)
    novs_unidades = db.query(Novedad).filter(
        Novedad.turno_id == turno.id, 
        Novedad.unidad_id != None
    ).order_by(Novedad.hora).all()

    if not novs_unidades:
        c.drawString(50, y, "Guardia Sin novedades en las unidades operativas.")
        y -= 15
    else:
        for n in novs_unidades:
            u = db.query(Unidad).filter_by(id=n.unidad_id).first()
            u_num = u.numero if u else "Borr."
            linea = f"[{n.hora.strftime('%H:%M')}] Unidad {u_num} - {n.tipo}: {n.detalle}"
            
            c.drawString(50, y, linea)
            y -= 15
            if y < 150: 
                c.showPage()
                y = 750

    y -= 15
    if y < 250: # Margen para que las áreas de sede quepan completas
        c.showPage()
        y = 750

    # --- SECCIÓN 4: ESTADO DE INFRAESTRUCTURA Y SEDE ---
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "4. ESTADO DE INFRAESTRUCTURA Y SEGURIDAD FISICA:")
    y -= 20
    
    # Frases automáticas para cuando NO hay novedades registradas
    areas_sede = {
        "CCTV": "Sistema de CCTV en Normal Funcionamiento.",
        "Infraestructura Sede": "Sede sin Novedades de Infraestructura.",
        "Seguridad Física": "Seguridad Física sin Novedades (Resguardo de Instalaciones OK)."
    }

    for area, texto_ok in areas_sede.items():
        c.setFont("Helvetica-Bold", 9)
        c.drawString(60, y, f"{area}:")
        
        # Buscamos si hay novedades de esta área específica (unidad_id es None)
        novedades_area = db.query(Novedad).filter_by(
            turno_id=turno.id, 
            unidad_id=None, 
            tipo=area
        ).all()

        if not novedades_area:
            c.setFont("Helvetica", 9)
            c.drawString(160, y, texto_ok)
            y -= 15
        else:
            y -= 12
            c.setFont("Helvetica", 9)
            for na in novedades_area:
                linea_sede = f"- [{na.hora.strftime('%H:%M')}] {na.detalle}"
                c.drawString(70, y, linea_sede)
                y -= 12
                if y < 100: c.showPage(); y = 750
            y -= 3 # Espacio extra tras lista de novedades

    # --- ESPACIO PARA FIRMAS AL FINAL ---
    if y < 150:  
        c.showPage()
        y = 750
        
    y_firma = 100 
    c.setLineWidth(1)
    c.setFont("Helvetica", 10)
    
    # Firma Izquierda (Analista)
    c.line(80, y_firma, 260, y_firma)
    c.drawCentredString(170, y_firma - 15, "Analista que Entrega")
    c.drawCentredString(170, y_firma - 28, nombre_titular)
    
    # Firma Derecha (Coordinador)
    coord_seg = db.query(Personal).filter_by(sede_id=turno.sede_id, cargo="Coord. de Seguridad").first()
    nombre_coord = coord_seg.nombre if coord_seg else "No asignado"

    c.line(340, y_firma, 520, y_firma)
    c.drawCentredString(430, y_firma - 15, "Coordinador de Seguridad")
    c.drawCentredString(430, y_firma - 28, nombre_coord)

    # Coletilla Final
    y_coletilla = 40
    c.setFont("Helvetica-BoldOblique", 8)
    c.setFillColorRGB(0.3, 0.3, 0.3)
    c.drawCentredString(306, y_coletilla, "Gerencia Corporativa de Seguridad, Monitoreo y GPS, Vigilancia Activa, Riesgo Cero")

    c.save()
    return buffer.getvalue()

# --- BARRA LATERAL ---

with st.sidebar:
    st.markdown(
        '<p style="text-align: center; margin-bottom: 5px; margin-top: 5px;">'
        '<img src="https://fospuca.com/wp-content/uploads/2018/08/fospuca.png" alt="Logo Fospuca" style="width: 100%; max-width: 120px; height: auto; display: block; margin-left: auto; margin-right: auto;">'
        '</p>',
         unsafe_allow_html=True
    )
    st.divider()

    if st.button("Estado General", width="stretch", type="primary" if st.session_state.vista_actual == "DASHBOARD" else "secondary"):
        st.session_state.vista_actual = "DASHBOARD"
        st.rerun()
        
    if st.button("Configuracion (Admin)", width="stretch", type="primary" if st.session_state.vista_actual == "CONFIG" else "secondary"):
        st.session_state.vista_actual = "CONFIG"
        st.rerun()

    st.write("**Flotas:**")
    for s_nombre in sedes_nombres:
        btn_type = "primary" if st.session_state.vista_actual == s_nombre else "secondary"
        if st.button(f"{s_nombre}", width="stretch", type=btn_type):
            st.session_state.vista_actual = s_nombre
            st.rerun()

# ====================================================================
# --- VISTA 1: CONFIGURADOR DE USUARIOS (ADMIN) ---
# ====================================================================
if st.session_state.vista_actual == "CONFIG":
    
    if not st.session_state.is_admin:
        empty_l, col_form, empty_r = st.columns([1, 2, 1])

        with col_form:
            st.markdown("<h1 style='text-align: center;'>Configuración del Sistema</h1>", unsafe_allow_html=True)    
            
            with st.form("login_admin"):
                admin_usr = st.text_input("Usuario Admin")
                admin_pass = st.text_input("Contraseña Admin", type="password")
                submit = st.form_submit_button("Aceptar", width="stretch")
        
                if submit:
                    if admin_usr == "Admin" and admin_pass == "M0n170r30**":
                        st.session_state.is_admin = True
                        st.rerun()
                    else:
                        st.error("Credenciales incorrectas.")
    else:
        if st.button("Cerrar Sesión de Administrador"):
            st.session_state.is_admin = False
            st.rerun()
            
        st.divider()
        st.subheader("Gestión de Operadores (Usuarios del Sistema)")
        
        with st.expander("➕ Crear Nuevo Usuario"):
            with st.form("crear_usuario"):
                col_u1, col_u2, col_u3 = st.columns(3)
                nu_nom = col_u1.text_input("Nombre y Apellido")
                nu_tel = col_u2.text_input("Teléfono")
                nu_ori = col_u3.selectbox("Sede Origen", ["-- Seleccionar --"] + sedes_nombres)
                
                col_u4, col_u5 = st.columns(2)
                nu_usr = col_u4.text_input("Usuario (Login)")
                nu_pas = col_u5.text_input("Contraseña", type="password")
                
                if st.form_submit_button("Guardar Analista"):
                    if nu_nom and nu_usr and nu_pas and nu_ori != "-- Seleccionar --":
                        existe = db.query(UsuarioSistema).filter_by(usuario=nu_usr).first()
                        if not existe:
                            db.add(UsuarioSistema(nombre=nu_nom, telefono=nu_tel, usuario=nu_usr, password=nu_pas, sede_origen=nu_ori))
                            db.commit()
                            st.success(f"Usuario {nu_usr} creado exitosamente.")
                            st.rerun()
                        else:
                            st.error("El nombre de usuario ya existe.")
                    else:
                        st.warning("Debe llenar todos los campos y seleccionar una sede.")

        st.write("Usuarios Registrados:")
        usuarios_db = db.query(UsuarioSistema).all()
        for u in usuarios_db:
            c_u1, c_u2 = st.columns([4, 1])
            c_u1.write(f"**{u.nombre}** (Usuario: {u.usuario}) | Sede: {u.sede_origen} | Tel: {u.telefono}")
            if c_u2.button("Eliminar", key=f"del_u_{u.id}"):
                db.delete(u)
                db.commit()
                st.rerun()

# ====================================================================
# --- VISTA 2: DASHBOARD GENERAL ---
# ====================================================================
elif st.session_state.vista_actual == "DASHBOARD":
    st.subheader("Estatus General de Flotas:")
    #st.title
    
    cols_monitoreo = st.columns(4)
    for i, s_nombre in enumerate(sedes_nombres):
        sede_db = db.query(Sede).filter_by(nombre=s_nombre).first()
        turno_act = db.query(TurnoSede).filter_by(sede_id=sede_db.id, activo=True).first()
        
        # 1. Contar unidades en ruta para esta sede
        en_ruta_sede = db.query(ControlDiario).join(Unidad).filter(
            Unidad.sede_id == sede_db.id,
            ControlDiario.hora_salida != None,
            ControlDiario.hora_entrada == None
        ).count()
        
        conteo_texto = f" | 🟢 En Ruta: {en_ruta_sede}" if en_ruta_sede > 0 else " | 🔵 En Resguardo"

        with cols_monitoreo[i % 4]:
            if turno_act:
                if turno_act.operador.startswith("PAUSA:"):
                    nom_pausa = turno_act.operador.split(":")[1]
                    st.markdown(f"<div class='sede-pausa-card'><b>{s_nombre}{conteo_texto}</b><br>⏸️ Pausa: {nom_pausa}</div>", unsafe_allow_html=True)
                elif turno_act.operador.startswith("RELEVO:"):
                    _, act, tit = turno_act.operador.split(":")
                    st.markdown(f"<div class='sede-activa-card'><b>{s_nombre}{conteo_texto}</b><br>🔄 Relevo: {act}</div>", unsafe_allow_html=True)
                else:
                    st.markdown(f"<div class='sede-activa-card'><b>{s_nombre}{conteo_texto}</b><br>🟢 On: {turno_act.operador}</div>", unsafe_allow_html=True)
            else:
                st.markdown(f"<div class='sede-inactiva-card'><b>{s_nombre}{conteo_texto}</b><br>Sin Analista</div>", unsafe_allow_html=True)

    st.divider()

    todas_unidades = db.query(Unidad).all()
    tot_ruta = tot_resguardo = tot_externo = tot_taller = tot_sede = 0
    
    for u in todas_unidades:
        if u.estatus_fijo == "TALLER":
            tot_taller += 1
            continue
        ctrl = db.query(ControlDiario).filter(ControlDiario.unidad_id == u.id).order_by(ControlDiario.id.desc()).first()
        if ctrl:
            if ctrl.hora_salida and not ctrl.hora_entrada:
                tot_ruta += 1
            elif ctrl.hora_salida and ctrl.hora_entrada:
                if ctrl.es_externo: tot_externo += 1
                else: tot_resguardo += 1
        else:
            tot_sede += 1
            
    total_fisico_sede = tot_sede + tot_resguardo
    
    col1, col2, col3, col4= st.columns(4)
    col1.markdown(f"<div class='kpi-card' style='border-color: #28a745;'><p class='kpi-num'>🟢 {tot_ruta}</p><p style='margin:0;'>En Ruta</p></div>", unsafe_allow_html=True)
    #col2.markdown(f"<div class='kpi-card' style='border-color: #007bff;'><p class='kpi-num'>🔵 {tot_resguardo}</p><p style='margin:0;'>Resguardo</p></div>", unsafe_allow_html=True)
    col2.markdown(f"<div class='kpi-card' style='border-color: #17a2b8;'><p class='kpi-num'>🌐 {tot_externo}</p><p style='margin:0;'>Resg. Externo</p></div>", unsafe_allow_html=True)
    col3.markdown(f"<div class='kpi-card' style='border-color: #dc3545;'><p class='kpi-num'>🔴 {tot_taller}</p><p style='margin:0;'>En Taller</p></div>", unsafe_allow_html=True)
    col4.markdown(f"<div class='kpi-card' style='border-color: #6c757d;'><p class='kpi-num'>⚪ {total_fisico_sede}</p><p style='margin:0;'>En Sede</p></div>", unsafe_allow_html=True)

    st.divider()
    
    col_graf1, col_graf2 = st.columns(2)

    with col_graf1:
        st.subheader("Ocupación de Flota en Ruta (%)")
        
        # 1. Preparar datos de unidades en ruta vs Total
        datos_cumplimiento = []
        for s_nom in sedes_nombres:
            s_obj = db.query(Sede).filter_by(nombre=s_nom).first()
            if s_obj:
                # Total de unidades de la sede
                total_flota = db.query(Unidad).filter_by(sede_id=s_obj.id).count()
                
                # Unidades actualmente en ruta
                en_ruta = db.query(ControlDiario).join(Unidad).filter(
                    Unidad.sede_id == s_obj.id,
                    ControlDiario.hora_salida != None,
                    ControlDiario.hora_entrada == None
                ).count()
                
                # Calcular porcentaje (evitando división por cero)
                porcentaje = (en_ruta / total_flota * 100) if total_flota > 0 else 0
                
                # Creamos una etiqueta que diga "5 de 10" para que aparezca al pasar el mouse
                etiqueta = f"{en_ruta} de {total_flota} Unid."
                
                datos_cumplimiento.append({
                    "Sede": s_nom,
                    "Porcentaje (%)": round(porcentaje, 1),
                    "Estado": etiqueta,
                    "Unidades": en_ruta # Esta es la cifra que queremos ver
                })
        
        # Crear DataFrame
        df_cumplimiento = pd.DataFrame(datos_cumplimiento)
        
        # Mostramos el gráfico
        # Nota: 'y' será el Porcentaje para la longitud de la barra
        # 'x' será la Sede
        st.bar_chart(
            df_cumplimiento.set_index("Sede"), 
            y="Porcentaje (%)", 
            horizontal=True, 
            color="#28a745"
        )
        
        # Mostramos una pequeña tabla resumen debajo para ver los números exactos
        # (Streamlit bar_chart básico no permite dibujar el texto fijo en la punta, 
        # pero con el tooltip al pasar el mouse verás el "5 de 10")
        with st.expander("Ver detalle numérico"):
            st.dataframe(df_cumplimiento[["Sede", "Estado", "Porcentaje (%)"]], hide_index=True, use_container_width=True)

    with col_graf2:
        st.subheader("Excesos de Velocidad (Hoy)")
        
        # 2. Preparar datos de excesos de velocidad
        hoy_str = datetime.now().strftime("%Y-%m-%d")
        excesos = db.query(Novedad).filter(
            Novedad.tipo == "Exceso Velocidad", 
            Novedad.hora >= f"{hoy_str} 00:00:00"
        ).all()
        
        conteo_excesos = {s: 0 for s in sedes_nombres}
        for ex in excesos:
            u_ex = db.query(Unidad).filter_by(id=ex.unidad_id).first()
            if u_ex:
                s_ex = db.query(Sede).filter_by(id=u_ex.sede_id).first()
                if s_ex:
                    conteo_excesos[s_ex.nombre] += 1
        
        # Crear DataFrame y mostrar gráfico de barras verticales
        data_vel = pd.DataFrame(list(conteo_excesos.items()), columns=['Sede', 'Infracciones'])
        st.bar_chart(data_vel.set_index('Sede'), color="#dc3545")


        
# ====================================================================
# --- VISTA 3: OPERACIÓN POR SEDE ---
# ====================================================================
elif st.session_state.vista_actual in sedes_nombres:
    sede_nombre = st.session_state.vista_actual
    sede_obj = db.query(Sede).filter_by(nombre=sede_nombre).first()
    turno_activo = db.query(TurnoSede).filter_by(sede_id=sede_obj.id, activo=True).first()
    
    # ---------------- FLUJO DE DESCARGA OBLIGATORIA ----------------
    # Si la variable 'pdf_listo' existe en sesión, la guardia ya se cerró, bloqueamos la app 
    # y forzamos al usuario a descargar y hacer clic en salir
    if 'pdf_listo' in st.session_state:
        st.title(f"Flota: {sede_nombre} - Guardia Finalizada")
        st.success("Guardia cerrada exitosamente en la base de datos. Por favor, descargue su reporte antes de abandonar la sede.")
        
        c_down1, c_down2 = st.columns([1, 1])
        c_down1.download_button("📥 Descargar Reporte PDF", st.session_state['pdf_listo'], st.session_state['pdf_filename'], "application/pdf",width="stretch")
        
        if c_down2.button("🚪 Finalizar y Liberar Sede", width="stretch", type="primary"):
            del st.session_state.auth_sedes[sede_nombre]
            if 'pdf_listo' in st.session_state: del st.session_state['pdf_listo']
            if 'pdf_filename' in st.session_state: del st.session_state['pdf_filename']
            st.rerun()
        st.stop()  # Detiene la ejecución del resto del código hasta que le dé salir
    # ---------------------------------------------------------------
    
    es_mi_sede = False
    operador_real = ""
    
    if turno_activo:
        if turno_activo.operador.startswith("RELEVO:"):
            operador_real = turno_activo.operador.split(":")[1]
        elif not turno_activo.operador.startswith("PAUSA:"):
            operador_real = turno_activo.operador
            
        if st.session_state.auth_sedes.get(sede_nombre) == operador_real and operador_real != "":
            es_mi_sede = True
        
    if not es_mi_sede:
        st.title(f"Control de Flota: {sede_nombre}")
        
        if turno_activo:
            if turno_activo.operador.startswith("PAUSA:"):
                titular = turno_activo.operador.split(":")[1]
                st.info(f"⏸️ Guardia pausada por **{titular}**. Ingrese sus credenciales para relevar/retomar.")
            elif turno_activo.operador.startswith("RELEVO:"):
                _, act, tit = turno_activo.operador.split(":")
                st.warning(f"⚠️ Sede operada actualmente por el relevo: **{act}** (Titular: {tit}). Debe pausar la sesión para permitir el acceso.")
            else:
                st.warning(f"⚠️ Sede bloqueada y operada por: **{turno_activo.operador}**. Debe pedirle que pause la sesión para poder hacer el relevo.")
        else:
            st.info("Flota Disponible. Inicie sesión para iniciar su guardia.")
            
        with st.form("login_sede"):
            c_usu = st.text_input("Usuario")
            c_pas = st.text_input("Contraseña", type="password")
            
            if st.form_submit_button("🔑 Iniciar Guardia / Retomar"):
                if c_usu == "Admin" and c_pas == "M0n170r30**":
                    if turno_activo:
                        if turno_activo.operador.startswith("PAUSA:"):
                            turno_activo.operador = turno_activo.operador.split(":")[1]
                        turno_activo.activo = False
                        turno_activo.hora_fin = datetime.now()
                        db.commit()
                        st.success("Guardia cerrada forzosamente por Administrador.")
                        st.rerun()
                    else:
                        st.warning("El administrador no puede operar sedes directamente.")
                else:
                    user_db = db.query(UsuarioSistema).filter_by(usuario=c_usu, password=c_pas).first()
                    if user_db:
                        if turno_activo:
                            if turno_activo.operador.startswith("PAUSA:"):
                                titular = turno_activo.operador.split(":")[1]
                                if user_db.nombre == titular:
                                    turno_activo.operador = titular
                                    n_log = Novedad(unidad_id=None, turno_id=turno_activo.id, tipo="Retoma de Guardia", detalle=f"El titular {titular} retomó el control.", operador=titular)
                                    db.add(n_log)
                                else:
                                    turno_activo.operador = f"RELEVO:{user_db.nombre}:{titular}"
                                    n_log = Novedad(unidad_id=None, turno_id=turno_activo.id, tipo="Relevo de Guardia", detalle=f"Relevo asumido por {user_db.nombre} (Sede: {user_db.sede_origen})", operador=user_db.nombre)
                                    db.add(n_log)
                                db.commit()
                                st.session_state.auth_sedes[sede_nombre] = user_db.nombre
                                st.rerun()
                            
                            elif turno_activo.operador == user_db.nombre or (turno_activo.operador.startswith("RELEVO:") and turno_activo.operador.split(":")[1] == user_db.nombre):
                                st.session_state.auth_sedes[sede_nombre] = user_db.nombre
                                st.rerun()
                                
                            else:
                                st.error("Sede bloqueada. Solicite al operador actual que pause la sesión antes de intentar el acceso.")
                        else:
                            nuevo_turno = TurnoSede(sede_id=sede_obj.id, operador=user_db.nombre)
                            db.add(nuevo_turno)
                            db.commit()
                            st.session_state.auth_sedes[sede_nombre] = user_db.nombre
                            st.rerun()
                    else:
                        st.error("Credenciales inválidas.")
        st.stop() 

    # --- ENTRA AL SISTEMA DE LA SEDE ---

    if turno_activo.operador.startswith("RELEVO:"):
        _, actual, titular = turno_activo.operador.split(":")
        
        # Dividimos en dos líneas: Título principal y subencabezado
        st.subheader(f"Flota: {sede_nombre}")
        st.subheader(f"Operador: {titular} (🔄 Relevo: {actual})")
        operador_actual = actual
    else:
        st.subheader(f"Flota: {sede_nombre}")
        st.subheader(f"Operador: {turno_activo.operador}")
        operador_actual = turno_activo.operador
    
    col_cierre1, col_cierre2, col_cierre3 = st.columns([5, 2, 2])
    
    with col_cierre2.popover("⏸️ PAUSAR SESIÓN", width="stretch"):
        st.write("**Pausar Guardia (Habilitar Relevo)**")
        motivo_pausa = st.text_input("Motivo de la pausa:")
        if st.button("Confirmar Pausa", width="stretch"):
            if motivo_pausa:
                tit = titular if turno_activo.operador.startswith("RELEVO:") else turno_activo.operador
                n_log = Novedad(unidad_id=None, turno_id=turno_activo.id, tipo="Pausa de Guardia", detalle=f"Pausado por {operador_actual}. Motivo: {motivo_pausa}", operador=operador_actual)
                db.add(n_log)
                turno_activo.operador = f"PAUSA:{tit}"
                db.commit()
                del st.session_state.auth_sedes[sede_nombre] 
                st.rerun()
            else:
                st.warning("Debe ingresar un motivo.")
            
    with col_cierre3:
        
            if st.button("🔴 CERRAR/TERMINAR", use_container_width=True):
                # 1. Finalizar el turno y registrar la hora de cierre
                turno_activo.activo = False
                hora_cierre = datetime.now()
                turno_activo.hora_fin = hora_cierre
                
                # Limpiar el nombre del operador si es un relevo
                if turno_activo.operador.startswith("RELEVO:"):
                    # Asumiendo que la estructura es RELEVO:ID:NOMBRE
                    partes = turno_activo.operador.split(":")
                    if len(partes) >= 3:
                        turno_activo.operador = partes[2]
                
                # Guardamos los cambios del turno (NO borramos unidades para el historial)
                db.commit()
                
                # 2. Determinar el prefijo según la hora para el nombre del archivo
                h = hora_cierre.hour
                prefix = "Diurna" if 6 <= h < 19 else "Nocturna"
                fecha_str = hora_cierre.strftime("%Y%m%d_%H%M")
                
                # 3. Generar el PDF (ahora encontrará toda la data porque no fue borrada)
                st.session_state['pdf_filename'] = f"Entrega_{prefix}_{sede_nombre}_{fecha_str}.pdf"
                
                pdf_data = generar_pdf_turno(turno_activo, sede_obj.nombre)
                st.session_state['pdf_listo'] = pdf_data
                
                # 4. Refrescar la aplicación
                st.rerun()



    tab1, tab2, tab_sede, tab3, tab4, tab5 = st.tabs(["Monitoreo","Operación Diaria",  "Novedades de Sede", "Personal", "Unidades", "Historial de Novedades"])


# ---------------- NOVEDADES DE SEDE (CCTV, SEGURIDAD, INFRAESTRUCTURA) ----------------

    with tab_sede:
        st.subheader("Control de Infraestructura y Seguridad Física")
        
        # Inicializamos las variables en session_state si no existen para poder limpiarlas
        if "s_tipo_val" not in st.session_state: st.session_state.s_tipo_val = "-- Seleccionar Área --"
        if "s_det_val" not in st.session_state: st.session_state.s_det_val = ""
        
        # Formulario de Registro
        with st.expander("➕ Registrar Evento (CCTV / Sede / Seguridad)", expanded=True):
            with st.form("form_novedad_sede", clear_on_submit=True):
                c_ns1, c_ns2, c_ns3 = st.columns([1.5, 1, 3])
                
                # Selector con la opción inicial solicitada
                tipo_ns = c_ns1.selectbox("Área", 
                                         ["-- Seleccionar Área --", "CCTV", "Infraestructura Sede", "Seguridad Física"],
                                         key="tipo_sede_input")
                
                hora_ns_raw = c_ns2.text_input("Hora (HH:MM)", value=datetime.now().strftime('%H:%M'))
                det_ns = c_ns3.text_input("Detalle de la Novedad", key="detalle_sede_input")
                
                if st.form_submit_button("Guardar Novedad de Sede", use_container_width=True):
                    if tipo_ns == "-- Seleccionar Área --":
                        st.warning("Por favor, seleccione un área válida.")
                    elif not det_ns:
                        st.warning("Debe describir el detalle de la novedad.")
                    else:
                        try:
                            h_obj_ns = datetime.strptime(hora_ns_raw, "%H:%M").time()
                            dt_ns = datetime.combine(datetime.today(), h_obj_ns)
                            
                            nueva_ns = Novedad(
                                unidad_id=None, 
                                turno_id=turno_activo.id, 
                                hora=dt_ns, 
                                tipo=tipo_ns, 
                                detalle=det_ns, 
                                operador=operador_actual
                            )
                            db.add(nueva_ns)
                            db.commit()
                            
                            st.success(f"Novedad de {tipo_ns} registrada exitosamente.")
                            # Al usar clear_on_submit=True en el form, los widgets se limpian solos.
                            # Forzamos rerun para mostrar la lista actualizada.
                            st.rerun()
                            
                        except ValueError:
                            st.error("Formato de hora inválido. Use HH:MM")

        #
        # --- VISUALIZACIÓN PERSONALIZADA POR COLORES ---
        st.divider()
        novs_sede_actual = db.query(Novedad).filter(
            Novedad.turno_id == turno_activo.id, 
            Novedad.unidad_id == None,
            Novedad.tipo.in_(["CCTV", "Infraestructura Sede", "Seguridad Física"])
        ).order_by(Novedad.hora).all()
        
        if not novs_sede_actual:
            st.info("No hay novedades de sede registradas en esta guardia.")
        else:
            for ns in novs_sede_actual:
                col_n1, col_n2, col_n3 = st.columns([8, 1, 1])
                
                # --- LÓGICA DE COLORES QUIRÚRGICA ---
                if ns.tipo == "CCTV":
                    # Azul (Info)
                    col_n1.info(f"**{ns.hora.strftime('%H:%M')}** | **{ns.tipo}** | {ns.detalle}")
                elif ns.tipo == "Infraestructura Sede":
                    # Amarillo (Warning/Advertencia)
                    col_n1.warning(f"**{ns.hora.strftime('%H:%M')}** | **{ns.tipo}** | {ns.detalle}")
                elif ns.tipo == "Seguridad Física":
                    # Rojo (Error/Alerta)
                    col_n1.error(f"**{ns.hora.strftime('%H:%M')}** | **{ns.tipo}** | {ns.detalle}")
                
                # Botones de Edición y Borrado (se mantienen igual para no dañar la funcionalidad)
                with col_n2.popover("✏️"):
                    opciones_sede = ["CCTV", "Infraestructura Sede", "Seguridad Física"]
                    idx_ns = opciones_sede.index(ns.tipo) if ns.tipo in opciones_sede else 0
                    
                    e_tipo_ns = st.selectbox("Área", opciones_sede, index=idx_ns, key=f"etns_{ns.id}")
                    e_hora_ns = st.text_input("Hora", value=ns.hora.strftime('%H:%M'), key=f"ehns_{ns.id}")
                    e_det_ns = st.text_input("Detalle", value=ns.detalle, key=f"edns_{ns.id}")
                    
                    if st.button("Actualizar", key=f"upns_{ns.id}", use_container_width=True):
                        try:
                            h_o = datetime.strptime(e_hora_ns, "%H:%M").time()
                            ns.tipo = e_tipo_ns
                            ns.hora = datetime.combine(ns.hora.date(), h_o)
                            ns.detalle = e_det_ns
                            db.commit()
                            st.rerun()
                        except ValueError:
                            st.error("Hora inválida")
                
                if col_n3.button("🗑️", key=f"delns_{ns.id}"):
                    db.delete(ns)
                    db.commit()
                    st.rerun()
                    
                    
    with tab5:
        
        st.subheader("Guardias Anteriores")
        st.write("Consulte las novedades y entregas de guardia de días anteriores.")
        
        fecha_busqueda = st.date_input("Seleccione la fecha a consultar", value=datetime.now().date())
        
        fecha_inicio = datetime.combine(fecha_busqueda, time.min)
        fecha_fin = datetime.combine(fecha_busqueda, time.max)
        
        turnos_dia = db.query(TurnoSede).filter(
            TurnoSede.sede_id == sede_obj.id,
            TurnoSede.hora_inicio >= fecha_inicio,
            TurnoSede.hora_inicio <= fecha_fin
        ).all()

        if not turnos_dia:
            st.info("No se encontraron guardias registradas en esta fecha.")
        else:
            for t in turnos_dia:
                estado_turno = f"Cerrada a las {t.hora_fin.strftime('%H:%M')}" if t.hora_fin else "EN CURSO"
                
                nom_hist = t.operador
                if t.operador.startswith("PAUSA:"):
                    nom_hist = t.operador.split(":")[1]
                elif t.operador.startswith("RELEVO:"):
                    nom_hist = t.operador.split(":")[2]
                
                with st.expander(f"Titular: {nom_hist} | {t.hora_inicio.strftime('%H:%M')} - {estado_turno}"):
                    novs_hist = db.query(Novedad).filter_by(turno_id=t.id).order_by(Novedad.hora).all()
                    if novs_hist:
                        for n in novs_hist:
                            if n.unidad_id is None:
                                st.markdown(f"**[{n.hora.strftime('%H:%M')}] SISTEMA** | {n.operador} | ℹ️ *{n.tipo}* - {n.detalle}")
                            else:
                                u_hist = db.query(Unidad).filter_by(id=n.unidad_id).first()
                                u_num = u_hist.numero if u_hist else "Borr."
                                st.markdown(f"**[{n.hora.strftime('%H:%M')}] Unidad {u_num}** | {n.operador} | 🚨 *{n.tipo}* - {n.detalle}")
                    else:
                        st.write("Sin novedades reportadas durante esta guardia.")

    # ---------------- MAESTRO DE PERSONAL ----------------
    with tab3:
            
        with st.expander("➕ Registrar Nuevo Personal en Base"):
            with st.form("form_personal"):
                c1, c2, c3, c4 = st.columns(4)
                p_nom = c1.text_input("Nombre")
                p_ced = c2.text_input("Cédula")
                p_tel = c3.text_input("Teléfono")
                p_cargo = c4.selectbox("Cargo", [
                    "-- Seleccionar --", "Conductor", "Mecánico", "Jefe de Contrato", "Jefe de Seguridad", 
                    "Jefe de Taller", "Coord. de Operaciones", "Coord. de Seguridad", 
                    "Supervisor de Guardia", "Supervisor de Taller"
                ])
                if st.form_submit_button("Guardar"):
                    if p_nom and p_cargo != "-- Seleccionar --":
                        db.add(Personal(nombre=p_nom, cedula=p_ced, telefono=p_tel, cargo=p_cargo, sede_id=sede_obj.id))
                        db.commit()
                        st.rerun()
                    else:
                        st.warning("Debe ingresar el nombre y seleccionar un cargo.")

        col_p_edit, col_p_del = st.columns(2)

        with col_p_edit:                

            with st.expander("✏️ Modificar"):
                pers_actuales = db.query(Personal).filter_by(sede_id=sede_obj.id).all()
                if pers_actuales:    
                    opciones_mod_p = ["-- Seleccionar --"] + [p.nombre for p in pers_actuales]
                    pers_a_editar = st.selectbox("Seleccione personal a modificar:", opciones_mod_p, key="mod_pers_sel")
                
                    if pers_a_editar != "-- Seleccionar --":
                        p_obj = next(p for p in pers_actuales if p.nombre == pers_a_editar)
                        st.write(f"Editando información de: **{p_obj.nombre}**")
                    
                        c_ep1, c_ep2, c_ep3, c_ep4 = st.columns(4)
                        n_nom = c_ep1.text_input("Nuevo Nombre", value=p_obj.nombre)
                        n_ced = c_ep2.text_input("Nueva Cédula", value=p_obj.cedula)
                        n_tel = c_ep3.text_input("Nuevo Teléfono", value=p_obj.telefono)
                    
                        lista_cargos_mod = ["Conductor", "Mecánico", "Jefe de Contrato", "Jefe de Seguridad", "Jefe de Taller", "Coord. de Operaciones", "Coord. de Seguridad", "Supervisor de Guardia", "Supervisor de Taller"]
                        idx_cargo = lista_cargos_mod.index(p_obj.cargo) if p_obj.cargo in lista_cargos_mod else 0
                        n_car = c_ep4.selectbox("Nuevo Cargo", lista_cargos_mod, index=idx_cargo)
                    
                        if st.button("Actualizar Información"):
                            if n_nom:
                                p_obj.nombre = n_nom
                                p_obj.cedula = n_ced
                                p_obj.telefono = n_tel
                                p_obj.cargo = n_car
                                db.commit()
                                st.success("Personal actualizado correctamente.")
                                st.rerun()
                            else:
                                st.error("El nombre no puede quedar vacío.")
                else:
                    st.info("No hay personal para modificar.")

        with col_p_del:

            with st.expander("🗑️ Eliminar"):
                pers_borrar = db.query(Personal).filter_by(sede_id=sede_obj.id).all()
                if pers_borrar:
                    opciones_del_p = ["-- Seleccionar --"] + [p.nombre for p in pers_borrar]
                    pers_a_borrar = st.selectbox("Seleccione el personal a eliminar:", opciones_del_p, key="del_pers_sel")
                    if st.button("Eliminar", key="btn_del_pers", width="stretch"):
                        if pers_a_borrar != "-- Seleccionar --":
                            p_borrar_obj = next(p for p in pers_borrar if p.nombre == pers_a_borrar)
                            if p_borrar_obj:
                                db.query(ControlDiario).filter_by(conductor_id=p_borrar_obj.id).delete()
                                db.delete(p_borrar_obj)
                                db.commit()
                                st.success(f"Personal {pers_a_borrar} eliminado.")
                                st.rerun()
                else:
                    st.info("No hay personal para eliminar.")

        pers_data = db.query(Personal).filter_by(sede_id=sede_obj.id).all()
        if pers_data: st.dataframe(pd.DataFrame([{"Nombre": p.nombre, "Cargo": p.cargo, "Tel": p.telefono} for p in pers_data]), width="stretch")

    # ---------------- MAESTRO DE UNIDADES ----------------
    with tab4:
        col_u_add,col_u_edit, col_u_del = st.columns(3)    

        with col_u_add:
            with st.expander("➕ Registrar Nueva Unidad"):
                with st.form("form_unidad"):
                    u_num = st.text_input("Número de Unidad")
                    if st.form_submit_button("Registrar", width="stretch"):
                        if u_num and not db.query(Unidad).filter_by(numero=u_num).first():
                            db.add(Unidad(numero=u_num, sede_id=sede_obj.id))
                            db.commit()
                            st.rerun()
                            
        with col_u_edit:
            with st.expander("✏️ Modificar"):
                unidades_actuales = db.query(Unidad).filter_by(sede_id=sede_obj.id).all()
                if unidades_actuales:
                    c_mod1, c_mod2 = st.columns(2)
                    
                    opciones_mod = ["-- Seleccionar --"] + [u.numero for u in unidades_actuales]
                    unidad_a_editar = c_mod1.selectbox("Unidad a Modificar:", opciones_mod, key="mod_sel")
                
                    if unidad_a_editar != "-- Seleccionar --":
                        nuevo_numero = c_mod2.text_input("Nuevo Número:", value=unidad_a_editar, key="mod_num")
                        if st.button("Actualizar", width="stretch"):
                            if nuevo_numero and nuevo_numero != unidad_a_editar:
                                if not db.query(Unidad).filter_by(numero=nuevo_numero).first():
                                    unidad_mod = db.query(Unidad).filter_by(numero=unidad_a_editar).first()
                                    unidad_mod.numero = nuevo_numero
                                    db.commit()
                                    st.success(f"Actualizada a {nuevo_numero}.")
                                    st.rerun()
                                else:
                                    st.error("Este número de unidad ya existe.")
                else:
                    st.info("No hay unidades para modificar.")

        with col_u_del:
            with st.expander("🗑️ Eliminar"):
                unidades_borrar = db.query(Unidad).filter_by(sede_id=sede_obj.id).all()
                if unidades_borrar:
                    opciones_del = ["-- Seleccionar --"] + [u.numero for u in unidades_borrar]
                    unidad_a_borrar = st.selectbox("Seleccione la unidad a eliminar:", opciones_del, key="del_sel")
                    if st.button("Eliminar", width="stretch"):
                        if unidad_a_borrar != "-- Seleccionar --":
                            u_borrar_obj = db.query(Unidad).filter_by(numero=unidad_a_borrar).first()
                            if u_borrar_obj:
                                db.query(Novedad).filter_by(unidad_id=u_borrar_obj.id).delete()
                                db.query(ControlDiario).filter_by(unidad_id=u_borrar_obj.id).delete()
                                db.delete(u_borrar_obj)
                                db.commit()
                                st.success(f"Unidad {unidad_a_borrar} eliminada.")
                                st.rerun()
                else:
                    st.info("No hay unidades para eliminar.")

        unid_data = db.query(Unidad).filter_by(sede_id=sede_obj.id).all()
        if unid_data: st.dataframe(pd.DataFrame([{"Unidad": u.numero, "Estatus General": u.estatus_fijo} for u in unid_data]), width="stretch")

    # ---------------- OPERACIÓN DIARIA ----------------
    with tab1:
        
        st.subheader("Novedades Monitoreo")
        novs_grales = db.query(Novedad).filter_by(turno_id=turno_activo.id, unidad_id=None).order_by(Novedad.hora).all()
        if novs_grales:
            for ng in novs_grales:
                st.info(f"**{ng.hora.strftime('%H:%M')}** |**{ng.tipo}** | {ng.operador} | {ng.detalle}")
        else:
            st.write("Sin novedades generales registradas en el sistema.")


    with tab2:        


        st.subheader("Numeros de Interes")
        personal_sede = db.query(Personal).filter_by(sede_id=sede_obj.id).all()
        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
        
        with col_m1:
            st.markdown("**Novedades Criticas**")
            for p in [p for p in personal_sede if p.cargo in ["Jefe de Contrato", "Jefe de Seguridad", "Jefe de Taller"]]: 
                st.markdown(f"<div class='directorio-box'>{p.cargo}<br><b>{p.nombre}</b> {p.telefono}</div>", unsafe_allow_html=True)
            
        with col_m2:
            st.markdown("**Novedades Medias**")
            for p in [p for p in personal_sede if p.cargo in ["Coord. de Seguridad","Coord. de Operaciones"]]: 
                st.markdown(f"<div class='directorio-box'>{p.cargo}<br><b>{p.nombre}</b> {p.telefono}</div>", unsafe_allow_html=True)
            
        with col_m3:
            st.markdown("**Supervisor(es) de Guardia**")
            sups_g = [p for p in personal_sede if p.cargo == "Supervisor de Guardia"]
            sel_g = st.multiselect("Asignar:", [p.nombre for p in sups_g], default=[p.nombre for p in sups_g if p.en_guardia], key="sg")
            if set(sel_g) != set([p.nombre for p in sups_g if p.en_guardia]):
                for p in sups_g: p.en_guardia = (p.nombre in sel_g)
                db.commit(); st.rerun()
            for s_nom in sel_g:
                tel = next(p.telefono for p in sups_g if p.nombre == s_nom)
                st.markdown(f"<div class='directorio-box-active'>{s_nom}<br> {tel}</div>", unsafe_allow_html=True)

        with col_m4:
            st.markdown("**Responsable de Taller**")
            sups_t = [p for p in personal_sede if p.cargo == "Mecánico"]
            sel_t = st.multiselect("Asignar:", [p.nombre for p in sups_t], default=[p.nombre for p in sups_t if p.en_guardia_taller], key="st")
            if set(sel_t) != set([p.nombre for p in sups_t if p.en_guardia_taller]):
                for p in sups_t: p.en_guardia_taller = (p.nombre in sel_t)
                db.commit(); st.rerun()
            for s_nom in sel_t:
                tel = next(p.telefono for p in sups_t if p.nombre == s_nom)
                st.markdown(f"<div class='directorio-box-active'>{s_nom}<br>{tel}</div>", unsafe_allow_html=True)

        st.subheader("Control Diario")
        
        unidades = db.query(Unidad).filter_by(sede_id=sede_obj.id).all()
        personal_sede = db.query(Personal).filter_by(sede_id=sede_obj.id).all()
        conductores = [p for p in personal_sede if p.cargo in ["Conductor", "Mecánico","Jefe de Contrato","Coord. de Operaciones","Jefe de Taller","Supervisor de Guardia" ]]


        for unit in unidades:

            exp_key = f"exp_{unit.id}"
            if exp_key not in st.session_state: st.session_state[exp_key] = False

            with st.container(): 
                c1, c2, c3, c4, c5 = st.columns([1, 1, 2.5, 1, 2.5])
                
                # AJUSTE VISUAL: MARGEN SUPERIOR PARA ALINEACIÓN

                if c1.button(f"{unit.numero}", key=f"btn_{unit.id}", width="stretch"):

                    st.session_state[exp_key] = not st.session_state[exp_key]
                    st.rerun()

                control_ultimo = db.query(ControlDiario).filter(
                    ControlDiario.unidad_id == unit.id
                ).filter(
                    (ControlDiario.hora_entrada == None) | (ControlDiario.hora_salida >= turno_activo.hora_inicio)
                ).order_by(ControlDiario.id.desc()).first()

                #control_ultimo = db.query(ControlDiario).filter(ControlDiario.unidad_id == unit.id).order_by(ControlDiario.id.desc()).first()
                
                estatus_visual = "EN SEDE"
                color = "en-sede"
                
                if unit.estatus_fijo == "TALLER":

                    estatus_visual = "TALLER"
                    color = "en-taller"
                    
                elif control_ultimo:

                    if control_ultimo.hora_salida and not control_ultimo.hora_entrada:
                        estatus_visual = "EN RUTA"
                        color = "en-ruta"
                        
                    elif control_ultimo.hora_salida and control_ultimo.hora_entrada:
                        if control_ultimo.es_externo:
                            estatus_visual = "RESG. EXTERNO"
                            color = "en-externo"
                            
                        else:
                            estatus_visual = "RESGUARDO"
                            color = "en-resguardo"

                c2.markdown(f'<div style="margin-top: 5px;"><div class="status-card {color}">{estatus_visual}</div></div>', unsafe_allow_html=True)
                
                if estatus_visual in ["EN SEDE", "RESGUARDO", "RESG. EXTERNO"]:
                    cond_nom = c3.selectbox(" ", ["-- Seleccionar --"] + [f"{p.nombre} ({p.cargo})" for p in conductores], key=f"sel_{unit.id}", label_visibility="collapsed")
                    
                    if cond_nom != "-- Seleccionar --":
                        p_nom_limpio = cond_nom.split(" (")[0]

                        tel = [p.telefono for p in conductores if p.nombre == p_nom_limpio][0]
                        tel_limpio = tel.split(" | ")[0]

                        c4.markdown(f"<div style='margin-top: 6px; font-size: 16px;'>{tel_limpio}</div>", unsafe_allow_html=True)
                
                    else:

                        c4.write("")
                    
                    with c5.popover("Acciones de Salida", width="stretch"):
                        
                        st.markdown("**Enviar a Reparacion:**")
                        h_actual = datetime.now().strftime('%H:%M')
                        hora_taller_raw = st.text_input("Hora ingreso a Taller (HH:MM)", value=h_actual, key=f"ht_raw_{unit.id}")
                        motivo_taller = st.text_input("Motivo del ingreso", key=f"mt_{unit.id}")

                        if st.button("Enviar a TALLER", key=f"taller_{unit.id}", width="stretch"):
                            if motivo_taller:
                                try:
                                   
                                    hora_taller_obj = datetime.strptime(hora_taller_raw, "%H:%M").time()
                                    dt_taller = datetime.combine(datetime.today(), hora_taller_obj)
                                    
                                    unit.estatus_fijo = "TALLER"
                                    n_nota = Novedad(unidad_id=unit.id, turno_id=turno_activo.id, hora=dt_taller, tipo="Ingreso a Taller", detalle=f"Enviada a Taller. Motivo: {motivo_taller}", operador=operador_actual)
                                    
                                    db.add(n_nota)
                                    db.commit()
                                    st.session_state[exp_key] = False 
                                    st.rerun()
                                except ValueError:
                                    st.error("Formato de hora inválido. Use HH:MM (ejemplo: 14:32)")
                            else:
                                st.warning("Debe indicar el motivo por el cual ingresa a Taller.")                     

                        #st.divider()
                        
                        if st.button("Registrar Salida", key=f"out_{unit.id}", width="stretch"):
                            
                            if cond_nom != "-- Seleccionar --":
                                p_nom_limpio = cond_nom.split(" (")[0]
                                cond_id = [p.id for p in conductores if p.nombre == p_nom_limpio][0]
                                db.add(ControlDiario(unidad_id=unit.id, conductor_id=cond_id, hora_salida=datetime.now()))

                                n_nota = Novedad(turno_id=turno_activo.id, unidad_id=unit.id,tipo="Salida de sede", detalle=f"Conductor: {p_nom_limpio}", operador=operador_actual)

                                db.add(n_nota)
                                db.commit()
                                st.session_state[exp_key] = False 
                                st.rerun()
                        
                        



                elif estatus_visual == "EN RUTA":
                    cond_obj = next(p for p in conductores if p.id == control_ultimo.conductor_id)
                    c3.markdown(f"<div style='margin-top: 10px;'>{cond_obj.nombre}</div>", unsafe_allow_html=True)
                    c4.markdown(f"<div style='margin-top: 10px;'>{cond_obj.telefono} </div>", unsafe_allow_html=True)
                    
                    with c5.popover("Registrar Entrada",width="stretch"):
                        hora_entrada_manual = st.time_input("Hora de Entrada", value=datetime.now().time(), key=f"he_{unit.id}")

                        if st.button("Entrada a Sede (Resguardo)", key=f"in_b_{unit.id}", width="stretch"):
                            dt_entrada = datetime.combine(datetime.today(), hora_entrada_manual)
                            control_ultimo.hora_entrada = dt_entrada
                            control_ultimo.es_externo = False
                            n_nota = Novedad(unidad_id=unit.id, turno_id=turno_activo.id, hora=dt_entrada, tipo="Ingresa a Sede", detalle="Resguardo", operador=operador_actual)
                            db.add(n_nota)
                            db.commit()
                            st.rerun()


                        if st.button("En RESGUARDO EXTERNO", key=f"in_e_{unit.id}", width="stretch"):
                            dt_entrada = datetime.combine(datetime.today(), hora_entrada_manual)
                            control_ultimo.hora_entrada = dt_entrada
                            control_ultimo.es_externo = True
                            n_nota = Novedad(unidad_id=unit.id, turno_id=turno_activo.id, hora=dt_entrada, tipo="En Resguardo Externo", detalle="En Resguardo Externo", operador=operador_actual)
                            db.add(n_nota)
                            db.commit()
                            st.rerun()

                elif estatus_visual == "TALLER":
                    
                    ultima_nov = db.query(Novedad).filter_by(
                        unidad_id=unit.id, 
                        tipo="Ingreso a Taller"
                    ).order_by(Novedad.hora.desc()).first()

                    if ultima_nov:
                        motivo = ultima_nov.detalle.replace("Enviada a Taller. Motivo: ", "")
                        fecha_ingreso = ultima_nov.hora.strftime('%d/%m %H:%M')
                    else:
                        motivo = "Sin registro de motivo."
                        fecha_ingreso = "--/-- --:--"

                    estilo_contenedor = "display: flex; flex-direction: column; justify-content: center; height: 45px;"

                    c3.markdown(f"""
                        <div style='{estilo_contenedor}'>
                            <div style='font-size: 16px; color: #dc3545; line-height: 1.2;'><b>{motivo}</b></div>
                        </div>
                    """, unsafe_allow_html=True)

                    c4.markdown(f"""
                        <div style='{estilo_contenedor}'>
                            <div style='font-size: 16px; color: #dc3545; line-height: 1.2;'><b>{fecha_ingreso}</b></div>
                        </div>
                    """, unsafe_allow_html=True)
                   
                    if c5.button("Dar de Alta (Operativa)", key=f"react_{unit.id}", width="stretch"):
                        unit.estatus_fijo = "OPERATIVA"
                        n_alta = Novedad(
                            unidad_id=unit.id, 
                            turno_id=turno_activo.id, 
                            hora=datetime.now(), 
                            tipo="Alta de Taller", 
                            detalle=f"Unidad reparada y puesta operativa.", 
                            operador=operador_actual
                        )
                        db.add(n_alta)
                        db.commit()
                        st.rerun()

                if st.session_state[exp_key]:
                    with st.expander("Novedades:", expanded=True):
                        col_nov1, col_nov2, col_nov3, col_nov4 = st.columns([1.5, 1, 3, 1])
                        tipo_nov = col_nov1.selectbox("Tipo", ["-- Seleccionar --", "Parada Larga", "Falla Mecánica", "Exceso Velocidad", "Cambio Chofer", "Surtir Combustible", "Prueba Mecánica", "Desvío", "Auxilio Vial"], key=f"tn_{unit.id}")                     
                        h_val = datetime.now().strftime('%H:%M')
                        hora_manual_raw = col_nov2.text_input("Hora (HH:MM)", value=h_val, key=f"hm_{unit.id}")
                    
                        det_nov = col_nov3.text_input("Detalles", key=f"dn_{unit.id}")
                    
                        if col_nov4.button("Guardar Nota", key=f"bn_{unit.id}", width="stretch"):
                            if tipo_nov != "-- Seleccionar --" and det_nov:
                                try:
                                    
                                    h_obj = datetime.strptime(hora_manual_raw, "%H:%M").time()
                                    dt_combinado = datetime.combine(datetime.today(), h_obj)
                                    db.add(Novedad(unidad_id=unit.id, turno_id=turno_activo.id, hora=dt_combinado, tipo=tipo_nov, detalle=det_nov, operador=operador_actual))
                                    db.commit()
                                    st.rerun()
                                    
                                except ValueError:
                                    st.error("Formato de hora inválido. Use HH:MM")
                            elif tipo_nov == "-- Seleccionar --":
                                st.warning("Seleccione un Tipo de Novedad.")
                            elif not det_nov:
                                st.warning("Ingrese los detalles.")
                    
                        novs_turno = db.query(Novedad).filter_by(unidad_id=unit.id, turno_id=turno_activo.id).order_by(Novedad.hora).all()
                        if novs_turno:
                            for n in novs_turno:
                                c_list1, c_list2, c_list3 = st.columns([8, 1, 1])
                                c_list1.info(f"**{n.hora.strftime('%H:%M')}** | **{n.tipo}** | {n.detalle}")
                            
                                with c_list2.popover("✏️"):
                                    st.markdown("**Editar Registro**")
                                    opc_editar = ["-- Seleccionar --", "Parada Larga", "Falla Mecánica", "Exceso Velocidad", "Cambio Chofer", "Surtir Combustible", "Prueba Mecánica", "Desvío", "Auxilio Vial", "Salida de Sede", "Ingreso a Taller", "Ingreso a Sede", "Ingreso a Resguardo Externo"]
                                    if n.tipo not in opc_editar: opc_editar.append(n.tipo)
                                    idx_t = opc_editar.index(n.tipo) if n.tipo in opc_editar else 0
                                
                                    e_tipo = st.selectbox("Tipo", opc_editar, index=idx_t, key=f"et_{n.id}")
                                
                                   
                                    e_h_val = n.hora.strftime('%H:%M')
                                    e_hora_raw = st.text_input("Hora (HH:MM)", value=e_h_val, key=f"eh_{n.id}")
                                
                                    e_det = st.text_input("Detalle", value=n.detalle, key=f"ed_{n.id}")
                                
                                    if st.button("Actualizar", key=f"eup_{n.id}", width="stretch"):
                                        if e_tipo != "-- Seleccionar --" and e_det:
                                            try:
                                                e_h_obj = datetime.strptime(e_hora_raw, "%H:%M").time()
                                                n.tipo = e_tipo
                                                n.detalle = e_det
                                                n.hora = datetime.combine(n.hora.date(), e_h_obj)
                                                db.commit()
                                                st.rerun()
                                            except ValueError:
                                                st.error("Hora inválida")
                            
                                if c_list3.button("🗑️", key=f"edel_{n.id}"):
                                    db.delete(n)
                                    db.commit()
                                    st.rerun()
                        else:
                            st.write("Hoja en blanco. Sin novedades en tu turno actual.")
