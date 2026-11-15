import java.nio.charset.StandardCharsets;
import java.sql.DriverManager;

/** JSON query helper with a narrow setup action for the disposable local database. */
class FixtureSql {
    public static void main(String[] args) throws Exception {
        String sql = new String(System.in.readAllBytes(), StandardCharsets.UTF_8);
        if (args.length == 2 && args[1].equals("--schedule-debate")) {
            var id = java.util.UUID.fromString(sql.strip());
            try (var connection = DriverManager.getConnection(args[0], "bullbear", "");
                 var statement = connection.prepareStatement(
                     "update debates set origin='SCHEDULED' where id=? and status='COMPLETED'")) {
                statement.setObject(1, id);
                if (statement.executeUpdate() != 1) throw new IllegalStateException("Fixture debate missing");
                System.out.println("true");
            }
            return;
        }
        if (!sql.stripLeading().toUpperCase(java.util.Locale.ROOT).startsWith("SELECT ")) {
            throw new IllegalArgumentException("Only fixture SELECT queries are allowed");
        }
        try (var connection = DriverManager.getConnection(args[0], "bullbear", "")) {
            connection.setReadOnly(true);
            try (var statement = connection.createStatement()) {
                statement.setQueryTimeout(5);
                try (var rows = statement.executeQuery(sql)) {
                    if (!rows.next()) throw new IllegalStateException("Fixture row missing");
                    System.out.println(rows.getString(1));
                }
            }
        }
    }
}
