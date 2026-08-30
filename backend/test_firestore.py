from google.cloud import firestore


db = firestore.Client(database="reach-memory")

doc_ref = db.collection("test").document("hello")

doc_ref.set({
    "message": "REACH Firestore is working",
    "status": "ok"
})

print("Firestore write successful!")
