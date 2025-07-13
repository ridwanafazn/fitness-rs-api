from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from sqlalchemy.orm import Session
from app import models, schemas
from app.dependencies import get_db, get_current_user

router = APIRouter(prefix="/routines", tags=["routines"])

@router.post("/", response_model=schemas.routine.RoutineOut)
def create_routine(routine: schemas.routine.RoutineCreate,
                   db: Session = Depends(get_db),
                   current_user: models.User = Depends(get_current_user)):
    db_routine = models.Routine(
        user_id=current_user.id,
        name=routine.name,
        description=routine.description,
        schedule=routine.schedule,
    )
    db.add(db_routine)
    db.commit()
    db.refresh(db_routine)
    return db_routine

@router.get("/", response_model=List[schemas.routine.RoutineOut])
def get_user_routines(db: Session = Depends(get_db),
                      current_user: models.User = Depends(get_current_user)):
    routines = db.query(models.Routine).filter(models.Routine.user_id == current_user.id).all()
    return routines

@router.get("/{routine_id}", response_model=schemas.routine.RoutineOut)
def get_routine(routine_id: int,
                db: Session = Depends(get_db),
                current_user: models.User = Depends(get_current_user)):
    routine = db.query(models.Routine).filter(models.Routine.id == routine_id,
                                             models.Routine.user_id == current_user.id).first()
    if not routine:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Routine not found")
    return routine