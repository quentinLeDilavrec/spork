package se.kth.spork.spoon.printer;

import se.kth.spork.spoon.ContentConflict;
import se.kth.spork.spoon.pcsinterpreter.ContentMerger;
import se.kth.spork.spoon.wrappers.RoledValue;
import se.kth.spork.util.LineBasedMerge;
import se.kth.spork.util.Pair;
import spoon.reflect.code.CtOperatorAssignment;
import spoon.reflect.declaration.CtElement;
import spoon.reflect.declaration.ModifierKind;
import spoon.reflect.path.CtRole;
import spoon.reflect.reference.CtPackageReference;
import spoon.reflect.reference.CtTypeReference;
import spoon.reflect.visitor.CtScanner;

import java.util.*;

/**
 * A pre-processor that must run before pretty-printing a merged tree. It does things like embedding conflict values
 * into literals and unsetting the source position of comments (so they get printed).
 *
 * @author Simon Larsén
 */
public class PrinterPreprocessor extends CtScanner {
    public static final String RAW_COMMENT_CONFLICT_KEY = "spork_comment_conflict";
    public static final String LOCAL_CONFLICT_MAP_KEY = "spork_local_conflict_map";
    public static final String GLOBAL_CONFLICT_MAP_KEY = "spork_global_conflict_map";
    public static final String CONTENT_CONFLICT_PREFIX = "__SPORK_CONFLICT_";

    private final List<String> importStatements;
    private final String activePackage;

    private final Map<String, Set<CtPackageReference>> refToPack;

    private int currentConflictId;

    // A mapping with content_conflict_id -> (left_side, right_side) mappings that are valid
    // in the entire source tree
    // TODO improve the pretty-printer such that this hack is redundant
    private final Map<String, Pair<String, String>> globalContentConflicts;

    public PrinterPreprocessor(List<String> importStatements, String activePackage) {
        this.importStatements = importStatements;
        this.activePackage = activePackage;
        refToPack = new HashMap<>();
        currentConflictId = 0;
        globalContentConflicts = new HashMap<>();
    }

    @Override
    public void scan(CtElement element) {
        if (element == null)
            return;

        element.putMetadata(GLOBAL_CONFLICT_MAP_KEY, Collections.unmodifiableMap(globalContentConflicts));

        @SuppressWarnings("unchecked")
        List<ContentConflict> conflicts = (List<ContentConflict>) element.getMetadata(ContentConflict.METADATA_KEY);

        if (conflicts != null) {
            conflicts.forEach(conf -> processConflict(conf, element));
        }

        super.scan(element);
    }

    /**
     * Process a conflict, and potentially mutate the element with the conflict. For example, values represented
     * as strings may have the conflict embedded directly into the literal.
     *
     * @param conflict A content conflict.
     * @param element  The element associated with the conflict.
     */
    @SuppressWarnings("unchecked")
    private void processConflict(ContentConflict conflict, CtElement element) {
        Object leftVal = conflict.getLeft().getValue();
        Object rightVal = conflict.getRight().getValue();

        // The local printer map, unlike the global printer map, is only valid in the scope of the
        // current CtElement. It contains conflicts for anything that can't be replaced with a conflict id,
        // such as operators and modifiers (as these are represented by enums)
        // TODO improve the pretty-printer such that this hack is redundant
        Map<String, Pair<String, String>> localPrinterMap = new HashMap<>();

        switch (conflict.getRole()) {
            case NAME:
            case VALUE:
                // these need to go into the global conflicts map, as the nodes in question aren't
                // always scanned separately by the printer (often it just calls `getSimpleName`)
                String conflictKey = CONTENT_CONFLICT_PREFIX + currentConflictId++;
                globalContentConflicts.put(conflictKey, Pair.of(leftVal.toString(), rightVal.toString()));
                element.setValueByRole(conflict.getRole(), conflictKey);
                break;
            case COMMENT_CONTENT:
                String rawLeft = (String) conflict.getLeft().getMetadata(RoledValue.Key.RAW_CONTENT);
                String rawRight = (String) conflict.getRight().getMetadata(RoledValue.Key.RAW_CONTENT);
                String rawBase = conflict.getBase().isPresent() ?
                        (String) conflict.getBase().get().getMetadata(RoledValue.Key.RAW_CONTENT) : "";

                Pair<String, Integer> rawConflict = LineBasedMerge.merge(rawBase, rawLeft, rawRight);
                assert rawConflict.second > 0 : "Comments without conflict should already have been merged";

                element.putMetadata(RAW_COMMENT_CONFLICT_KEY, rawConflict.first);
                break;
            case IS_UPPER:
                if (leftVal.equals(true)) {
                    localPrinterMap.put("extends", Pair.of("extends", "super"));
                } else {
                    localPrinterMap.put("super", Pair.of("super", "extends"));
                }
                break;
            case MODIFIER:
                Collection<ModifierKind> leftMods = (Collection<ModifierKind>) leftVal;
                Collection<ModifierKind> rightMods = (Collection<ModifierKind>) rightVal;
                Set<ModifierKind> leftVisibilities = ContentMerger.categorizeModifiers(leftMods).first;
                Set<ModifierKind> rightVisibilities = ContentMerger.categorizeModifiers(rightMods).first;

                if (leftVisibilities.isEmpty()) {
                    // use the right-hand visibility in actual tree to force something to be printed
                    Collection<ModifierKind> mods = element.getValueByRole(CtRole.MODIFIER);
                    ModifierKind rightVis = rightVisibilities.iterator().next();
                    mods.add(rightVis);
                    element.setValueByRole(CtRole.MODIFIER, mods);
                    localPrinterMap.put(rightVis.toString(), Pair.of("", rightVis.toString()));
                } else {
                    String leftVisStr = leftVisibilities.iterator().next().toString();
                    String rightVisStr = rightVisibilities.isEmpty()
                            ? "" : rightVisibilities.iterator().next().toString();
                    localPrinterMap.put(leftVisStr, Pair.of(leftVisStr, rightVisStr));
                }
                break;
            case OPERATOR_KIND:
                assert leftVal.getClass() == rightVal.getClass();

                String leftStr = OperatorHelper.getOperatorText(leftVal);
                String rightStr = OperatorHelper.getOperatorText(rightVal);

                if (element instanceof CtOperatorAssignment) {
                    leftStr += "=";
                    rightStr += "=";
                }
                localPrinterMap.put(leftStr, Pair.of(leftStr, rightStr));
                break;
            default:
                throw new IllegalStateException("Unhandled conflict: " + leftVal + ", " + rightVal);
        }

        if (!localPrinterMap.isEmpty()) {
            element.putMetadata(LOCAL_CONFLICT_MAP_KEY, localPrinterMap);
        }
    }
}
