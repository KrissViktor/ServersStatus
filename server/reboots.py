from pydantic import BaseModel,Field


class RebootEvent(BaseModel):
    event_id:int=Field(ge=0,le=65535)
    record_id:int=Field(ge=0)
    at:float=Field(ge=0,allow_inf_nan=False)
    source:str=Field(max_length=100)
    kind:str=Field(pattern='^(planned|unexpected|boot|shutdown|update)$')
    message:str=Field(default='',max_length=350)
    reason_code:str=Field(default='',max_length=80)
    process:str=Field(default='',max_length=160)


class RebootHistory(BaseModel):
    status:str=Field(pattern='^(checking|available|unavailable)$')
    checked_at:float|None=Field(default=None,ge=0,allow_inf_nan=False)
    events:list[RebootEvent]=Field(default_factory=list,max_length=12)
