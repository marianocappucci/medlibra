"""Placeholder PaymentPort: no cobra ni reintegra automaticamente.

No hay proveedor de pago elegido todavia. La confirmacion de la sena la
hace un admin a mano (efectivo, transferencia, link de MercadoPago enviado
por fuera) via los endpoints mark-paid/mark-failed/refund -- decision
acordada con el usuario, ver DECISIONS.md ADR-XXX.
"""
import logging

from libragenda import Deposit

logger = logging.getLogger("medlibra.payments")


class ManualPaymentPort:
    def request_charge(self, deposit: Deposit) -> None:
        logger.info("deposit charge requested (manual): %s amount=%s", deposit.id, deposit.amount)

    def request_refund(self, deposit: Deposit) -> None:
        logger.info("deposit refund requested (manual): %s amount=%s", deposit.id, deposit.amount)
