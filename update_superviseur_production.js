// Script MongoDB pour mettre à jour les rôles en production
// À exécuter sur votre base de données en ligne

// Option 1 : Mettre à jour le compte jfrancois.ouoba@gmail.com
db.users.updateOne(
  { email: "jfrancois.ouoba@gmail.com" },
  { $set: { role: "superviseur" } }
);

print("✓ Compte jfrancois.ouoba@gmail.com mis à jour en superviseur");

// Vérifier la mise à jour
var user1 = db.users.findOne(
  { email: "jfrancois.ouoba@gmail.com" },
  { email: 1, nom: 1, role: 1, _id: 0 }
);
print("\nCompte 1:");
printjson(user1);

// Option 2 : Mettre à jour le compte admin.test@comptable.fr s'il existe
var adminExists = db.users.findOne({ email: "admin.test@comptable.fr" });

if (adminExists) {
  db.users.updateOne(
    { email: "admin.test@comptable.fr" },
    { $set: { role: "superviseur" } }
  );
  print("\n✓ Compte admin.test@comptable.fr mis à jour en superviseur");
  
  var user2 = db.users.findOne(
    { email: "admin.test@comptable.fr" },
    { email: 1, nom: 1, role: 1, _id: 0 }
  );
  print("\nCompte 2:");
  printjson(user2);
} else {
  print("\n⚠ Compte admin.test@comptable.fr n'existe pas encore.");
  print("Vous devez d'abord créer ce compte sur le site en ligne.");
  print("Il sera automatiquement superviseur grâce au code mis à jour.");
}

print("\n=== Mise à jour terminée ===");
