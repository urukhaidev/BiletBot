from calendar import monthrange
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Search(BaseModel):
    query: str = ""
    origin: str = Field(pattern=r"^[A-Z]{3}$")
    destination: str = Field(pattern=r"^[A-Z]{3}$")
    origin_name: str
    destination_name: str
    anywhere: bool = False
    trip_type: Literal["OW", "RT"] = "OW"
    trip_type_explicit: bool = True
    date_from: date | None = None
    date_to: date | None = None
    month: date | None = None
    depart_date_min: date | None = None
    depart_date_max: date | None = None
    duration_min: int = Field(default=7, ge=1, le=365)
    duration_max: int = Field(default=10, ge=1, le=365)
    direct: bool = False
    max_changes: int | None = Field(default=None, ge=0, le=10)
    baggage: bool = False
    max_price: int = Field(default=999999, gt=0)

    @model_validator(mode="after")
    def validate_dates(self):
        if sum([self.date_from is not None, self.month is not None,
                self.depart_date_min is not None]) != 1:
            raise ValueError("Нужна дата, месяц или диапазон вылета")
        if bool(self.depart_date_min) != bool(self.depart_date_max):
            raise ValueError("Укажите обе границы диапазона")
        if self.depart_date_min and self.depart_date_min > self.depart_date_max:
            raise ValueError("Некорректный диапазон дат")
        if self.date_to and (self.trip_type != "RT" or not self.date_from or self.date_to <= self.date_from):
            raise ValueError("Дата возврата должна быть после вылета")
        if self.duration_min > self.duration_max:
            raise ValueError("Некорректная длительность поездки")
        if self.month and self.month.day != 1:
            raise ValueError("Месяц должен начинаться с первого числа")
        return self

    def last_departure(self):
        if self.month:
            return self.month.replace(day=monthrange(self.month.year, self.month.month)[1])
        return self.date_from or self.depart_date_max

    @property
    def mode(self):
        if self.trip_type == "OW":
            return "OW_DATE" if self.date_from else "OW_MONTH" if self.month else "OW_RANGE"
        if self.date_to:
            return "RT_DATES"
        return "RT_DATE_DUR" if self.date_from else "RT_MONTH" if self.month else "RT_RANGE"

    def variants(self):
        if not self.trip_type_explicit:
            return [self.model_copy(update={"trip_type": "OW"}), self.model_copy(update={"trip_type": "RT"})]
        return [self]

    def matches(self, ticket: dict, today: date):
        departure = date.fromisoformat(ticket["departure_at"][:10])
        if departure < today:
            return False
        if ticket["origin_city_iata"] != self.origin or (not self.anywhere and ticket["destination_city_iata"] != self.destination):
            return False
        if self.date_from and departure != self.date_from:
            return False
        if self.month and (departure.year, departure.month) != (self.month.year, self.month.month):
            return False
        if self.depart_date_min and not self.depart_date_min <= departure <= self.depart_date_max:
            return False
        if self.direct and int(ticket["number_of_changes"]) != 0:
            return False
        if self.max_changes is not None and int(ticket["number_of_changes"]) > self.max_changes:
            return False
        if self.baggage and (not ticket.get("baggage_code") or ticket["baggage_code"].startswith("0PC")):
            return False
        if float(ticket["value"]) <= 0 or float(ticket["value"]) > self.max_price:
            return False
        if self.trip_type == "RT":
            returning = date.fromisoformat(ticket["return_at"][:10])
            if self.anywhere:
                return returning > departure and (returning.year, returning.month) == (departure.year, departure.month)
            if self.date_to:
                return returning == self.date_to
            duration = ticket.get("trip_duration")
            if duration is None:
                duration = (returning - departure).days
            return self.duration_min <= int(duration) <= self.duration_max
        return not ticket.get("return_at")
