"""Alicuota de IVA por servicio.

LibraGenda's `Service` no tiene campo de impuestos por diseno -- el motor
de turnos es generico y no sabe de facturacion -- asi que la alicuota vive
en una tabla propia de MedLibra, mismo patron que `service_prices`.

**Por que existe.** Hasta esta tabla, `billing._split_iva` asumia 21% fijo
para todo. En un producto de salud eso esta mal en el caso normal: la
mayoria de las prestaciones medicas estan **exentas** de IVA, y algunas
tributan al 10,5%. El 21% de antes no era una decision fiscal, era un
placeholder que el propio docstring marcaba como pendiente de revisar con
un contador.

**Que decide este modulo y que no.** Decide *donde* se guarda la alicuota
y *cuales* son validas; **no** decide que alicuota le corresponde a cada
prestacion -- eso lo carga el usuario con su contador. El default de la
instancia sale de `business_settings.default_iva_rate`, inicializado en
21% para no cambiarle el comportamiento a ninguna instalacion existente.

**Por que la lista de alicuotas es cerrada, y no es cosmetico.** ARCA
espera un `Id` de `AlicIva`, y `libracore.arca_wsfe._iva_id()` lo deriva
del porcentaje con `_IVA_ID.get(round(pct, 1), _IVA_ID.get(round(pct), 5))`:
ante un porcentaje que no conoce **cae al Id 5, que es 21%**. O sea que una
alicuota arbitraria (13%, por ejemplo) no fallaria: se declararia como 21%
ante ARCA, sin ningun error a la vista. Por eso se valida acá contra el
mismo mapa que usa LibraCore.
"""
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from libragenda.sqlalchemy_repository import Base

EXENTO = Decimal("0")

# Las cuatro que `libracore.arca_wsfe._IVA_ID` sabe mapear a un Id de ARCA
# (3=0%, 4=10,5%, 5=21%, 6=27%). Cualquier otra se declararia como 21%.
ALLOWED_RATES = (EXENTO, Decimal("0.105"), Decimal("0.21"), Decimal("0.27"))

DEFAULT_RATE = Decimal("0.21")


class InvalidIvaRate(ValueError):
    """La alicuota pedida no es una de las que ARCA sabe mapear."""

    def __init__(self, rate: Decimal) -> None:
        permitidas = ", ".join(f"{r * 100:g}%" for r in ALLOWED_RATES)
        super().__init__(
            f"alicuota {rate} no permitida -- ARCA solo mapea {permitidas}"
        )
        self.rate = rate


def validate_rate(rate: Decimal) -> Decimal:
    """Normaliza y valida una alicuota. Lanza `InvalidIvaRate` si no es una
    de las que ARCA sabe declarar."""
    normalized = Decimal(rate).normalize()
    for allowed in ALLOWED_RATES:
        if normalized == allowed.normalize():
            return allowed
    raise InvalidIvaRate(rate)


class ServiceIvaRateRow(Base):
    __tablename__ = "service_iva_rates"

    service_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("services.id"), primary_key=True
    )
    rate: Mapped[Decimal] = mapped_column(Numeric(6, 4))


def _to_dict(row: ServiceIvaRateRow) -> dict:
    return {"service_id": row.service_id, "rate": row.rate}


class IvaRateRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def set_rate(self, service_id: str, rate: Decimal) -> dict:
        """Crea o actualiza la alicuota de este servicio."""
        rate = validate_rate(rate)
        with self.session_factory.begin() as session:
            row = session.get(ServiceIvaRateRow, service_id)
            if row is None:
                row = ServiceIvaRateRow(service_id=service_id, rate=rate)
                session.add(row)
            else:
                row.rate = rate
            session.flush()
            return _to_dict(row)

    def get(self, service_id: str) -> dict | None:
        with self.session_factory() as session:
            row = session.get(ServiceIvaRateRow, service_id)
            return _to_dict(row) if row else None

    def delete(self, service_id: str) -> None:
        """Saca la alicuota propia del servicio: vuelve a valer el default
        de la instancia."""
        with self.session_factory.begin() as session:
            row = session.get(ServiceIvaRateRow, service_id)
            if row is None:
                raise KeyError(service_id)
            session.delete(row)

    def list_all(self) -> list[dict]:
        with self.session_factory() as session:
            rows = session.scalars(select(ServiceIvaRateRow)).all()
            return [_to_dict(row) for row in rows]

    def resolve(self, service_id: str, default: Decimal) -> Decimal:
        """Alicuota que le corresponde a este servicio: la propia si tiene,
        si no la default de la instancia."""
        row = self.get(service_id)
        return Decimal(row["rate"]) if row is not None else Decimal(default)
